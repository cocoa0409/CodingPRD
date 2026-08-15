# Construction Closeout API — Product Requirements Document

## 1. Introduction

The last phase of a construction project is where schedule risk, money, and legal exposure converge. Work that looked complete at a distance turns out to have deficiencies; every trade must be walked, corrected, and re-inspected; the owner must formally accept the building before anyone may speak of final payment; and long after the keys change hands, warranty callbacks keep arriving. General-contractor closeout teams run this gauntlet today with spreadsheets and email, and the failure modes are expensive: retainage released too early, lien waivers accepted out of sequence, a life-safety deficiency forgotten because nobody could see the whole board.

This document specifies the Construction Closeout API, the system of record for that pipeline. It tracks a project from mobilization through punch operations, substantial-completion determination, beneficial occupancy, closeout-package assembly, final lien waivers and retainage release, and the warranty window that follows close. The design leans on posture-driven phase gates (each project phase admits only specific operations), server-computed money (clients never state a release amount), segregation of duties between the party who corrects a deficiency and the party who signs it off, and a controllable logical clock that governs every temporal rule. All endpoints are mounted under the `/closeout` path prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles: `GCProjectManager`, `GCInspector`, `OwnerRep`, and `SubcontractorRep`. A request with a missing or invalid header, or an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the endpoint's allowed roles is rejected with `ERR_FORBIDDEN` (HTTP 403); §4 lists the authorized roles for every endpoint.

Role identity works in two distinct ways. When `X-User-Role` is `GCProjectManager`, `GCInspector`, or `OwnerRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `ready_by_user_id` or `verified_by_user_id` on a punch item — but never compares it against any entity's `id`. When `X-User-Role` is `SubcontractorRep`, `X-User-ID` is the `id` of the acting TradePackage; ownership checks on any resource that references a trade package compare the resource's `trade_package_id` field to `X-User-ID`.

That identity partition drives the responsible-party rule. Three operations are reserved for the party responsible for a trade's work: marking a punch item ready for review, submitting a closeout document, and submitting a lien waiver. On all three, a `SubcontractorRep` may act only on their own trade and only when that trade is `SUBCONTRACTOR`; a `GCProjectManager` may act as responsible party only on `SELF_PERFORMED` trades (the GC's self-performed correction work). Any other pairing is rejected with `ERR_NOT_RESPONSIBLE_PARTY` (HTTP 403).

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock; it is the one timestamp in the system not sourced from the logical clock of §2.4.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

Endpoints that return lists accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to those bounds rather than rejected, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. `offset` states how many items to skip and defaults to 0; a negative `offset` is treated as 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; because `created_at` is stamped from the logical clock (§2.5), resources created at the same clock reading are ordered by creation sequence. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally accept resource-appropriate equality filters — depending on the resource, some combination of `project_id`, `trade_package_id`, `lead_inspector_id`, `status`, `severity`, `punch_walk_id`, `doc_type`, and `kind` — each narrowing the result set before pagination is applied. The assignment is: trade packages filter by `project_id`; punch walks by `project_id`, `trade_package_id`, and `lead_inspector_id`; punch items by `project_id`, `trade_package_id`, `status`, `severity`, and `punch_walk_id`; closeout documents by `project_id`, `trade_package_id`, `doc_type`, and `status`; training sessions by `project_id`, `trade_package_id`, and `status`; retainage releases by `project_id`, `kind`, and `status`; and warranty cases by `project_id` and `status`. Unrecognized query parameters are ignored.

### 2.4. The Logical Clock

Every temporal rule in this system is evaluated against a server-side logical clock, never against wall-clock time. Before any client call has been handled, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `GCProjectManager`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant (ISO 8601 UTC) and returns the new reading as `current_utc`. The supplied instant is adopted verbatim — no ordering rule prevents moving the clock to a reading earlier than the current one — and here as everywhere a datetime supplied without an explicit offset is read as UTC. Scheduling rules, walk and session start gates, occupancy ordering, and the warranty window all consult this clock and no other source of time.

### 2.5. Common Resource Properties

All eight resources — Project, TradePackage, PunchWalk, PunchItem, CloseoutDocument, TrainingSession, RetainageRelease, and WarrantyCase — share four system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording the logical-clock reading (§2.4) at the moment the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed to the current logical-clock reading on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by one on every mutation of the resource — including mutations cascaded from other resources.

Every state-machine transition, counter change, derived-flag recomputation, or ledger adjustment that changes at least one stored field of an entity counts as a mutation of that entity and therefore refreshes its `updated_at` and increments its `version`; a derived-field recomputation that leaves every field of the entity unchanged is not a mutation and touches nothing. This holds even when the mutation was triggered indirectly — for instance when a release event mutates its parent project. (Requesting a retainage release counts as a mutation of the parent project even though no project field visibly changes; §3.6.)

Business datetime fields — `scheduled_start` and `scheduled_end` on walks and sessions, `substantial_completion_date`, `warranty_start_date`, `beneficial_occupancy_date`, `closed_at`, `ready_at`, `reported_at`, `sla_due_at`, and the clock endpoint's `current_utc` — are emitted as ISO 8601 UTC at whole-second precision.

### 2.6. Money, Cents, and the Retainage Ledger

All monetary values are integer cents; fractional cents never appear anywhere in the API. Where a computation produces a fractional cent, the result is rounded half-up to a whole cent.

Each project carries a small retainage ledger. At project creation the system computes `retainage_held_cents` as the product of `contract_value_cents` and `retainage_pct`, rounded half-up to a whole cent, and then freezes it: the held figure is rounded exactly once, at creation, and every downstream release calculation derives from that stored value rather than re-multiplying the raw inputs. `retainage_paid_cents` begins at zero and accumulates the `amount_cents` of the project's releases as they reach `PAID`. `retainage_outstanding_cents` is always the held figure minus the paid figure, so it starts equal to `retainage_held_cents`.

The ledger is compensating. Approving a release moves money from outstanding to paid; voiding an already-paid release moves the same amount back, so an approve-then-void sequence leaves both figures exactly as they stood before the approval. Because every release event mutates the project, each one also increments the project's `version`.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control; no other endpoint accepts a version field, and clients must not send one elsewhere.

First, requesting a retainage release requires the request body to carry `expected_project_version`, holding the client's last observed `version` of the project the release is drawn against. If the project's current `version` has advanced since that observation — for example because another writer created or voided a release, which changes the project's ledger without changing its phase — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), since a new release legitimately supersedes the client's stale view of the project's release ledger.

Second, rescheduling a training session requires `expected_training_session_version` matching the session's current `version`. A reschedule leaves the session in `SCHEDULED`, so a later request carrying a stale version would observe a state identical to the one it expects and would otherwise apply cleanly on top of an unseen reschedule; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Derived Counters, Eligibility Flags, and Cascading Phase Changes

Several fields are never written by clients; the server derives them. On a project, `open_life_safety_count`, `open_major_count`, and `open_minor_count` count the project's punch items of the corresponding severity whose status is `OPEN` or `READY_FOR_REVIEW`. A ready-for-review item still blocks; only the terminal states `VERIFIED` and `VOIDED` release a counter. On a trade package, `open_item_count` applies the same predicate across all severities. These counters rise at item creation, fall at verification and at voiding, and are recomputed on read.

Two boolean flags summarize readiness. A project's `sc_eligible` reflects the substantial-completion gates of §3.4 and is recomputed whenever the blocking counters or walk completion change. A trade's `closeout_ready` reflects the package-completion rule of §3.5 and is recomputed on punch-item verification and voiding, on document approval, on training conduct, and on waiver acceptance. Recomputations are themselves mutations: when a derived flag flips, the owning entity's `updated_at` refreshes and its `version` increments.

One cascade crosses the aggregate boundary entirely. When the last unready trade's `closeout_ready` flips to true while the project is in `CLOSEOUT_IN_PROGRESS`, the server advances the project to `FINAL_RELEASE_PENDING` on its own — no explicit client request targets the project — and that automatic transition increments the project's `version` like any other.

### 2.9. Resource Addressing and Cross-Reference Integrity

Paths address one resource at a time through a single identifier — `{projectId}`, `{tradePackageId}`, `{walkId}`, `{itemId}`, `{docId}`, `{sessionId}`, `{releaseId}`, or `{caseId}`. An identifier that matches no existing resource is rejected with `ERR_NOT_FOUND` (HTTP 404), whether it arrives in the path or in the request body. A request addressed to a path this API does not define receives the same `ERR_NOT_FOUND` treatment (HTTP 404); a defined path invoked with an unsupported method receives `ERR_NOT_FOUND` at HTTP 405.

Belonging is enforced across references. On punch-item, punch-walk, closeout-document, and training-session creation, the supplied `trade_package_id` must belong to the referenced `project_id`; otherwise the request fails with `ERR_TRADE_NOT_IN_PROJECT` (HTTP 422). When a punch item optionally cites the walk during which it was found, that `punch_walk_id` must likewise belong to the same project, or creation fails with `ERR_WALK_NOT_IN_PROJECT` (HTTP 422).

### 2.10. The Validation Pipeline

A single request can violate several rules at once, and which error comes back is not arbitrary: the server evaluates checks in a fixed priority order and reports the first failure. From first to last:

1. Authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`).
2. Endpoint authorization — the role is allowed on this endpoint (`ERR_FORBIDDEN`).
3. Responsible-party ownership on the three responsible-party operations (`ERR_NOT_RESPONSIBLE_PARTY`).
4. Verification duties — segregation-of-duties and the escalation rule (`ERR_SEGREGATION_OF_DUTIES`, `ERR_VERIFICATION_ESCALATED`).
5. Request schema — the body is a JSON object, required fields present (a field sent as null counts as absent), enum values valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`).
6. Existence of every referenced resource (`ERR_NOT_FOUND`).
7. Optimistic-concurrency staleness on the two OCC endpoints (`ERR_STALE_VERSION`).
8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed).
9. The life-safety gate at the substantial-completion boundary (`ERR_OPEN_LIFE_SAFETY_ITEMS`).
10. Clock-based temporal rules — scheduling in the past, completing or conducting before the window opens, occupancy dated before substantial completion, warranty window expiry.
11. Remaining domain constraints — the major/minor SC gates, walk completion, inspector overlap, the reschedule cap, the room buffer, duplicate trades, document singularity and satisfaction, attendance, waiver phase-gating and absorption, occupancy idempotence and ordering, final-release payment before close.
12. Cross-reference integrity (`ERR_TRADE_NOT_IN_PROJECT`, `ERR_WALK_NOT_IN_PROJECT`).
13. Fiscal rules — release-kind reuse and zero-amount releases (`ERR_RELEASE_KIND_ALREADY_USED`, `ERR_RELEASE_AMOUNT_ZERO`).

One practical qualification: where a check cannot be evaluated without first fetching a resource — the responsible-type side of the responsible-party rule (§2.1), and segregation of duties and the escalation rule on a path-addressed punch item — the fetch happens first, so a path identifier that matches nothing surfaces as `ERR_NOT_FOUND` ahead of those checks. The portion of the responsible-party rule that needs only the caller's identity and the request — a `SubcontractorRep` whose `X-User-ID` does not match the addressed or submitted trade package — is still evaluated at step 3.

The ordering is observable behavior: an unauthenticated caller learns nothing about resource state, and a stale version surfaces before any state-machine complaint.

## 3. Business Logic & Workflows

### 3.1. Project Setup and Trade Mobilization

A `GCProjectManager` opens a closeout engagement by creating a project with a `name`, a `contract_value_cents` of at least 1000 cents, and a `retainage_pct` — the fraction of the contract value withheld as retainage, which must be greater than zero and no more than 0.25, a quarter of the contract at most. Two optional policies govern later behavior: `reduction_policy`, spelled `STANDARD` or `ADJUSTED` and defaulting to `STANDARD`, selects how the substantial-completion release treats lingering minor items; `warranty_sla_mode`, spelled `CALENDAR` or `BUSINESS` and defaulting to `CALENDAR`, selects how warranty response windows count days. Missing required fields, invalid enum spellings, or out-of-range numbers are rejected with `ERR_INVALID_REQUEST`.

A new project begins in `MOBILIZED`. Creation freezes `retainage_held_cents` per §2.6, initializes `retainage_paid_cents` and all three open-item counters to zero, sets `sc_eligible` and `beneficial_occupancy_registered` to false, zeroes `sc_rejection_count`, and leaves `substantial_completion_date`, `warranty_start_date`, and `closed_at` null.

While the project remains `MOBILIZED`, the manager registers its trade packages; registration attempted in any later phase is rejected with `ERR_INVALID_STATE`. Each package names its `project_id`, a `trade_name` drawn from `ELECTRICAL`, `PLUMBING`, `HVAC`, `DRYWALL`, `FLOORING`, `ROOFING`, `PAINTING`, or `CONCRETE` — unique within the project, with a repeat rejected as `ERR_DUPLICATE_TRADE` — and a `responsible_type` of `SUBCONTRACTOR` or `SELF_PERFORMED`. The `subcontractor_org` name is required exactly when the responsible type is `SUBCONTRACTOR`; for a `SELF_PERFORMED` package it is optional — absent, or supplied and stored as given. A fresh package starts with `lien_waiver_status` at `NONE`, `open_item_count` at zero, and every derived flag — `has_completed_walk`, `om_doc_approved`, `warranty_doc_approved`, `asbuilt_doc_approved`, `has_conducted_training`, and `closeout_ready` — false.

Beginning punch operations moves the project from `MOBILIZED` to `PUNCH_ACTIVE`. The move is permitted only once at least one trade package exists; with zero packages it fails with `ERR_NO_TRADE_PACKAGES`. The transition increments the project's `version`.

### 3.2. Pre-Punch Walks and Punch Item Intake

With punch active, the `GCProjectManager` schedules a pre-punch walk for a trade by supplying `project_id`, the `trade_package_id` to be walked (it must belong to that project — `ERR_TRADE_NOT_IN_PROJECT`), the `lead_inspector_id` (an opaque identifier for the inspector who will lead the walk), and a window from `scheduled_start` to `scheduled_end`. Walks may be created only while the project is `PUNCH_ACTIVE`. Three rules govern the window: it may not begin before the current logical clock (`ERR_SCHEDULED_IN_PAST`); its end must fall at least 30 minutes after its start — a half-hour being the minimum credible walk — with anything shorter rejected as `ERR_INVALID_REQUEST`; and it may not collide with another walk led by the same inspector — every existing walk under that `lead_inspector_id` counts, whatever its status and whichever project it belongs to. Collision uses half-open semantics: a window covers its start instant up to but not including its end instant, so a walk beginning at exactly the moment the same inspector's earlier walk ends is permissible, while any positive shared time is rejected with `ERR_WALK_OVERLAP`. A newly scheduled walk sits in `SCHEDULED`.

Completing a walk — a `GCInspector` or the `GCProjectManager` — moves it from `SCHEDULED` to `COMPLETED`, but only once the logical clock has reached its `scheduled_start`; an early attempt is rejected with `ERR_WALK_NOT_STARTED`. Completion flips the trade package's `has_completed_walk` to true and triggers a recomputation of the project's substantial-completion eligibility.

Punch items record the deficiencies a walk, or any other observation, turns up. A `GCInspector` or the `GCProjectManager` creates one — again only while the project is `PUNCH_ACTIVE` — with a short `title`, a `severity` of `LIFE_SAFETY`, `MAJOR`, or `MINOR`, a three-part location (`location_building`, `location_floor`, `location_area`), and a mandatory `photo_ref` attaching photographic evidence. The payload's `trade_package_id` designates the responsible party, and an optional `punch_walk_id` cites the walk that found the item; the cited walk must belong to the same project, or creation fails with `ERR_WALK_NOT_IN_PROJECT`. A new item starts `OPEN` and immediately blocks: the project's counter for that severity (`open_life_safety_count`, `open_major_count`, or `open_minor_count`) and the responsible trade's `open_item_count` each increase by one, and the eligibility flags of §2.8 are recomputed.

### 3.3. Correction, Re-Inspection, and Sign-Off

When the responsible party believes an item is fixed, they mark it ready — a `SubcontractorRep` for their own `SUBCONTRACTOR` trade, or the `GCProjectManager` for a `SELF_PERFORMED` trade, with any other pairing rejected as `ERR_NOT_RESPONSIBLE_PARTY`. Two further gates apply. The project must be in one of the five working phases — `PUNCH_ACTIVE`, `SC_REVIEW`, `SUBSTANTIALLY_COMPLETE`, `CLOSEOUT_IN_PROGRESS`, or `FINAL_RELEASE_PENDING` — and any other phase is rejected as `ERR_INVALID_STATE`. And the item's trade must already have completed its walk; without one the mark-ready fails with `ERR_WALK_INCOMPLETE`. Success moves the item from `OPEN` to `READY_FOR_REVIEW` and stamps `ready_by_user_id` with the caller's `X-User-ID` and `ready_at` with the logical clock. A ready item still blocks the project: only terminal states release the counters.

Verification is the inspector's sign-off, moving the item from `READY_FOR_REVIEW` to `VERIFIED` under the same five-phase gate. Two duty rules guard it. First, the verifier's `X-User-ID` must differ from the recorded `ready_by_user_id` — the person who declared the work fixed may not certify it, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, once an item's `rejection_count` has reached two or more, the sign-off escalates: only a `GCProjectManager` may verify it, and a `GCInspector` attempt is rejected with `ERR_VERIFICATION_ESCALATED`. A successful verification stamps `verified_by_user_id` with the caller, decreases the project's severity counter and the trade's `open_item_count` by one each, and recomputes both `sc_eligible` and `closeout_ready` — including the cascade that can move a project waiting in `CLOSEOUT_IN_PROGRESS` into `FINAL_RELEASE_PENDING` (§3.5).

A failed re-inspection sends the item back. A `GCInspector` — and only that role — rejects a ready item with a mandatory `reason`, whose absence is an `ERR_INVALID_REQUEST`; the item returns to `OPEN`, its `rejection_count` increases by one, the reason is stored in `rejection_reason`, and `ready_by_user_id` is cleared to null (the earlier `ready_at` is retained) so a fresh correction cycle begins under a different pair of hands.

Finally, an item that should never have existed — a duplicate, or an entry error — can be voided by the `GCProjectManager`, but only while the project is still `PUNCH_ACTIVE` (`ERR_INVALID_STATE` in any later phase). Voiding moves the item from `OPEN` to `VOIDED`, decreases the same two counters by one each, and recomputes `sc_eligible` and `closeout_ready`. `VERIFIED` and `VOIDED` are the item's terminal states.

### 3.4. Substantial Completion and Beneficial Occupancy

Substantial completion is the pivot of the whole closeout: it fixes the warranty start date and unlocks occupancy registration, closeout work, and money movement. The project's `sc_eligible` flag tracks readiness continuously — true exactly when `open_life_safety_count` is zero, `open_major_count` is zero, `open_minor_count` is no more than five (five open minor items pass; a sixth fails), and every trade package of the project has completed its pre-punch walk.

Requesting a substantial-completion review moves the project from `PUNCH_ACTIVE` to `SC_REVIEW`. The four gates are enforced in a fixed, safety-first order: any blocking life-safety item rejects the request with `ERR_OPEN_LIFE_SAFETY_ITEMS`; then any blocking major item rejects it with `ERR_OPEN_MAJOR_ITEMS`; then an open minor count above the allowance rejects it with `ERR_TOO_MANY_OPEN_MINOR_ITEMS`; and only then does walk completion surface, with any unwalked trade rejecting the request as `ERR_WALK_INCOMPLETE`. A granted request increments the project's `version`.

The determination itself belongs to the `OwnerRep`, who submits `approved` as true or false. Approval re-checks the same four gates at determination time — the request may be days old, and the counts may have moved — applying the same codes in the same order; on success the project moves to `SUBSTANTIALLY_COMPLETE` and both `substantial_completion_date` and `warranty_start_date` are stamped with the current logical clock, so the warranty clock starts at the SC instant. A rejection requires a `rejection_note` (its absence is an `ERR_INVALID_REQUEST`), returns the project to `PUNCH_ACTIVE` for another correction cycle, and increases `sc_rejection_count` by one. Either determination increments the project's `version`.

While the project is `SUBSTANTIALLY_COMPLETE`, the owner registers beneficial occupancy by supplying an `occupancy_date`. Registration is single-shot — a second call is rejected with `ERR_OCCUPANCY_ALREADY_REGISTERED` — and the supplied date may not fall earlier than `substantial_completion_date` (`ERR_OCCUPANCY_BEFORE_SC`, HTTP 422). Success sets `beneficial_occupancy_registered` to true, stores the date as `beneficial_occupancy_date`, and increments the project's `version`.

Starting closeout moves the project from `SUBSTANTIALLY_COMPLETE` to `CLOSEOUT_IN_PROGRESS`. The move requires occupancy to be registered first; without it the request fails with `ERR_OCCUPANCY_NOT_REGISTERED`, and as always the transition increments the project's `version`.

### 3.5. The Closeout Package: Documents, Training, and Lien Waivers

Closeout assembles, for every trade, three approved documents, at least one conducted training session, and an accepted unconditional lien waiver. A trade's `closeout_ready` flag summarizes the package: it is true exactly when `open_item_count` is zero, `om_doc_approved` and `warranty_doc_approved` and `asbuilt_doc_approved` are all true, `has_conducted_training` is true, and the waiver stands `ACCEPTED` with type `UNCONDITIONAL`. The cascade built on it matters most: whenever a recomputation flips the last unready trade's `closeout_ready` to true while the project sits in `CLOSEOUT_IN_PROGRESS`, the project advances itself to `FINAL_RELEASE_PENDING` per §2.8. Four operations can touch off that cascade — a document approval, a conducted training session, a waiver acceptance, and a punch-item verification.

Documents are submitted by the responsible party — a `SubcontractorRep` for their own trade or the `GCProjectManager` for `SELF_PERFORMED` work, with other pairings rejected as `ERR_NOT_RESPONSIBLE_PARTY` — by supplying `project_id`, `trade_package_id`, a `doc_type` of `OM_MANUAL`, `WARRANTY_DOC`, or `AS_BUILT`, and a `file_ref` pointing at the document. Two singularity rules apply per trade and document type: at most one document may sit pending — that is, in `SUBMITTED` — at a time, with a second rejected as `ERR_DOC_ALREADY_PENDING`; and once a document of that type has been `APPROVED`, the pair is satisfied and further submissions are rejected with `ERR_DOC_TYPE_ALREADY_SATISFIED`. Submission itself carries no project-phase gate — only the decision operations do (below). Each accepted submission is numbered by the server: its `revision` is the count of prior documents for the same trade and document type, plus one.

Document decisions rest with the `GCProjectManager` and only while the project is in `CLOSEOUT_IN_PROGRESS` or `FINAL_RELEASE_PENDING`; at any other phase the attempt is rejected as `ERR_INVALID_STATE`. Approval moves the document from `SUBMITTED` to `APPROVED`, flips the trade's corresponding flag — `om_doc_approved`, `warranty_doc_approved`, or `asbuilt_doc_approved` according to `doc_type` — and recomputes `closeout_ready`. Rejection requires a `rejection_reason` (`ERR_INVALID_REQUEST` without one), stores it on the document as `rejection_reason`, and moves the document to `REJECTED`; the revision loop then runs through a brand-new document for the same trade and type, numbered one higher. `APPROVED` and `REJECTED` are both terminal for the document itself.

Training and demonstration sessions are scheduled by the `GCProjectManager` while the project is `SUBSTANTIALLY_COMPLETE` or `CLOSEOUT_IN_PROGRESS`. Each session names a `system_name` — say, the controls of a particular air-handling unit — a `location_room`, and a window from `scheduled_start` to `scheduled_end`. The end must be later than the start, and the start may not lie before the current logical clock (`ERR_SCHEDULED_IN_PAST`). Rooms turn over slowly: a 30-minute buffer must separate any two sessions booked into the same `location_room` — every existing session in that room counts, whatever its status and whichever project it belongs to — so one session's end and the next session's start must stand at least thirty minutes apart (a gap of exactly thirty minutes passes), with outright overlap forbidden; a violation is rejected with `ERR_SESSION_ROOM_CONFLICT`.

A scheduled session can be moved, but sparingly. Rescheduling requires `expected_training_session_version` per §2.7 and supplies a new `scheduled_start` and `scheduled_end`; the new start must not lie in the past, and the room buffer is re-evaluated against the other sessions in that room while excluding the session being moved. The cap is hard: `reschedule_count` must still be below two, so a session already rescheduled twice rejects a third attempt with `ERR_RESCHEDULE_LIMIT`. A successful reschedule replaces the window, increases `reschedule_count` by one, and increments the session's `version`.

Conducting the session is possible once the logical clock has reached its `scheduled_start` — earlier attempts fail with `ERR_SESSION_NOT_STARTED` — and requires an `attendee_count` of at least one (`ERR_NO_ATTENDEES` otherwise). The count is stored, the session moves from `SCHEDULED` to `CONDUCTED`, the trade's `has_conducted_training` flips to true, and `closeout_ready` is recomputed.

The lien-waiver lifecycle runs on the trade package. The responsible party submits the waiver with a `waiver_type` of `CONDITIONAL` or `UNCONDITIONAL`, an `amount_cents` greater than zero, and a `file_ref`; the server stores them as `lien_waiver_type`, `lien_waiver_amount_cents`, and `lien_waiver_file_ref` (all three null until the first submission), and moves `lien_waiver_status` from `NONE` to `SUBMITTED`. Submission is accepted in any of the five working phases from `PUNCH_ACTIVE` through `FINAL_RELEASE_PENDING` (`ERR_INVALID_STATE` outside them), and after a rejection the same operation resubmits, moving `REJECTED` back to `SUBMITTED` and overwriting the stored waiver fields; a submission attempted while a waiver already stands `SUBMITTED` — still awaiting its decision — is rejected with `ERR_INVALID_STATE`. Acceptance, though, is absorbing: once `lien_waiver_status` stands at `ACCEPTED`, any further submission is rejected with `ERR_WAIVER_ALREADY_ACCEPTED`. Submissions and decisions alike mutate the trade package and increment its `version`.

The waiver decision belongs to the `GCProjectManager`, requires the waiver to be currently `SUBMITTED` (any other status is `ERR_INVALID_STATE`), and carries a `decision` of `ACCEPT` or `REJECT`. Acceptance is phase-gated by waiver type. A `CONDITIONAL` waiver may be accepted once the project has reached `SUBSTANTIALLY_COMPLETE`, `CLOSEOUT_IN_PROGRESS`, or `FINAL_RELEASE_PENDING`; an `UNCONDITIONAL` waiver may be accepted only in `CLOSEOUT_IN_PROGRESS` or `FINAL_RELEASE_PENDING`; acceptance attempted in any other phase fails with `ERR_WAIVER_NOT_ACCEPTABLE_STATE`. A `REJECT` decision requires a `rejection_reason` (`ERR_INVALID_REQUEST` without one) and lands the waiver in `REJECTED`, from which resubmission remains possible. An acceptance recomputes `closeout_ready` — note that only an `UNCONDITIONAL` acceptance can complete that flag — and may thereby touch off the project cascade.

### 3.6. Retainage Releases and Project Close

Money leaves the ledger through releases, requested by the `GCProjectManager` with a `project_id`, a `kind`, and the `expected_project_version` required by §2.7. Two kinds exist, each bound to its phase: a `REDUCTION` — the partial release customarily paid at substantial completion — may be requested only while the project is `SUBSTANTIALLY_COMPLETE`, and a `FINAL` only while it is `FINAL_RELEASE_PENDING`; a request of either kind in the wrong phase is rejected as `ERR_INVALID_STATE`. Each kind may be used at most once in a live state: if a release of the same kind already exists in `REQUESTED` or `PAID`, the new request fails with `ERR_RELEASE_KIND_ALREADY_USED`.

The client never states an amount; the server computes `amount_cents` at creation. For a `REDUCTION`, the base is one-half of `retainage_held_cents`, rounded half-up to a whole cent — derived from the frozen held figure, never re-computed by multiplying the raw contract value, the retainage fraction, and one-half in a single step. Under the `STANDARD` policy the release amount is exactly that base, whatever minor items remain open. Under the `ADJUSTED` policy, 25,000 cents — 250 dollars — are withheld for each blocking minor item (severity `MINOR`, status `OPEN` or `READY_FOR_REVIEW`, counted at request time), subtracted from the base with the result floored at zero; identical project data therefore yields a smaller or equal release under `ADJUSTED`. If a `REDUCTION`'s computed amount lands exactly on zero, creation is rejected with `ERR_RELEASE_AMOUNT_ZERO`, under either policy. For a `FINAL` release, the amount is `retainage_outstanding_cents` at request time: the frozen held figure minus the sum of `amount_cents` over the project's `PAID` releases, with merely `REQUESTED` or already `VOIDED` releases contributing nothing; a `FINAL` release is never rejected on amount grounds and is created even if that figure is zero. A created release starts in `REQUESTED`, and its creation increments the project's `version`.

Approval belongs to the `OwnerRep`. Approving a `REQUESTED` release moves it to `PAID`, increases the project's `retainage_paid_cents` by the release's `amount_cents`, decreases `retainage_outstanding_cents` by the same amount, and increments the project's `version`. The `GCProjectManager` may instead void a release. Voiding a still-`REQUESTED` release moves no money — the payment never happened. Voiding an already-`PAID` release is a clawback: paid decreases and outstanding increases by the release amount, leaving the ledger exactly as if the payment had never occurred. `PAID` and `VOIDED` are terminal — an attempt to approve or void an already-`VOIDED` release fails with `ERR_INVALID_STATE`.

Closing the project is the `GCProjectManager`'s final act. It requires the project to stand in `FINAL_RELEASE_PENDING` and a `FINAL` release to exist in `PAID` status; without one, the close is rejected with `ERR_FINAL_RELEASE_NOT_PAID`. A successful close stamps `closed_at` with the logical clock, moves the project to `CLOSED` — its terminal state — and increments its `version`.

### 3.7. Warranty Callbacks After Closeout

Once the project is `CLOSED`, the warranty window governs callbacks. A case is admissible only while the logical clock reads no later than `warranty_start_date` plus 365 days, and the interval is closed at its end: a report landing exactly at the final instant is accepted, while one a single second later is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422). Reporting against a project that is not yet `CLOSED` fails with `ERR_PROJECT_NOT_CLOSED` (HTTP 409).

The `OwnerRep` reports a case with a `project_id`, a `title`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, and a `description` of the issue. The case starts in `REPORTED`, stamps `reported_at` with the logical clock, and leaves `sla_due_at` null until triage.

Triage, performed by the `GCProjectManager`, moves the case from `REPORTED` to `TRIAGED`, sets `severity` from the request payload — replacing the value given at report time — and computes `sla_due_at` according to the project's `warranty_sla_mode`. The response window is one day for `CRITICAL`, seven days for `MAJOR`, and thirty days for `MINOR`. Under `CALENDAR` mode the due instant is simply the triage instant plus that many days, with the time of day preserved; weekend days count toward the window. Under `BUSINESS` mode the count advances by business days instead, skipping Saturdays and Sundays: the triage instant is day zero, the first day counted is the next business day, and the time of day is again preserved, so the same triage instant yields a later due timestamp whenever weekends intervene. A `MAJOR` case triaged on Friday, 4 September 2026 at 10:00 UTC, for example, falls due on 11 September 2026 at 10:00 UTC under `CALENDAR`, but not until 15 September 2026 at 10:00 UTC under `BUSINESS`. SLA timestamps are ISO 8601 UTC at second precision.

Resolution moves a `TRIAGED` case to `RESOLVED` and stores a `resolution_note`, which is mandatory (`ERR_INVALID_REQUEST` without one). Denial is available from either `REPORTED` or `TRIAGED`, requires a `denial_reason` (`ERR_INVALID_REQUEST` without one), stores it as `denial_reason`, and lands the case in `DENIED`. `RESOLVED` and `DENIED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition — return `200 OK`. The table below is a summary only: request payloads, response payloads, and side effects are defined by the narratives of §2 and §3, not here. "Any" in the role column means all four roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/closeout/projects` | Create a project (`MOBILIZED`; retainage held computed and frozen) | GCProjectManager |
| GET | `/closeout/projects/{projectId}` | Get a project | Any |
| POST | `/closeout/projects/{projectId}/begin-punch` | Begin punch operations (`MOBILIZED` → `PUNCH_ACTIVE`) | GCProjectManager |
| POST | `/closeout/projects/{projectId}/request-sc-review` | Request substantial-completion review (`PUNCH_ACTIVE` → `SC_REVIEW`) | GCProjectManager |
| POST | `/closeout/projects/{projectId}/determine-substantial-completion` | Owner determination: approve (→ `SUBSTANTIALLY_COMPLETE`) or reject (→ `PUNCH_ACTIVE`) | OwnerRep |
| POST | `/closeout/projects/{projectId}/register-beneficial-occupancy` | Register beneficial occupancy while `SUBSTANTIALLY_COMPLETE` | OwnerRep |
| POST | `/closeout/projects/{projectId}/start-closeout` | Start closeout (`SUBSTANTIALLY_COMPLETE` → `CLOSEOUT_IN_PROGRESS`) | GCProjectManager |
| POST | `/closeout/projects/{projectId}/close` | Close the project (`FINAL_RELEASE_PENDING` → `CLOSED`) | GCProjectManager |
| POST | `/closeout/trade-packages` | Register a trade package (project must be `MOBILIZED`) | GCProjectManager |
| GET | `/closeout/trade-packages/{tradePackageId}` | Get a trade package | Any |
| GET | `/closeout/trade-packages` | List trade packages | Any |
| POST | `/closeout/trade-packages/{tradePackageId}/lien-waiver-submission` | Submit or resubmit the trade's lien waiver | SubcontractorRep, GCProjectManager |
| POST | `/closeout/trade-packages/{tradePackageId}/lien-waiver-decision` | Accept or reject a submitted lien waiver | GCProjectManager |
| POST | `/closeout/punch-walks` | Schedule a pre-punch walk for a trade | GCProjectManager |
| GET | `/closeout/punch-walks/{walkId}` | Get a punch walk | Any |
| GET | `/closeout/punch-walks` | List punch walks | Any |
| POST | `/closeout/punch-walks/{walkId}/complete` | Complete a walk (`SCHEDULED` → `COMPLETED`) | GCInspector, GCProjectManager |
| POST | `/closeout/punch-items` | Create a punch item with location, photo, and responsible party | GCInspector, GCProjectManager |
| GET | `/closeout/punch-items/{itemId}` | Get a punch item | Any |
| GET | `/closeout/punch-items` | List punch items | Any |
| POST | `/closeout/punch-items/{itemId}/mark-ready` | Mark an item ready for review (`OPEN` → `READY_FOR_REVIEW`) | SubcontractorRep, GCProjectManager |
| POST | `/closeout/punch-items/{itemId}/verify` | Sign off an item (`READY_FOR_REVIEW` → `VERIFIED`) | GCInspector, GCProjectManager |
| POST | `/closeout/punch-items/{itemId}/reject` | Fail re-inspection (`READY_FOR_REVIEW` → `OPEN`) | GCInspector |
| POST | `/closeout/punch-items/{itemId}/void` | Void an erroneous item (`OPEN` → `VOIDED`) | GCProjectManager |
| POST | `/closeout/closeout-documents` | Submit a closeout document (O&M, warranty, or as-built) | SubcontractorRep, GCProjectManager |
| GET | `/closeout/closeout-documents/{docId}` | Get a closeout document | Any |
| GET | `/closeout/closeout-documents` | List closeout documents | Any |
| POST | `/closeout/closeout-documents/{docId}/approve` | Approve a document (`SUBMITTED` → `APPROVED`) | GCProjectManager |
| POST | `/closeout/closeout-documents/{docId}/reject` | Reject a document with reason (`SUBMITTED` → `REJECTED`) | GCProjectManager |
| POST | `/closeout/training-sessions` | Schedule a training/demonstration session | GCProjectManager |
| GET | `/closeout/training-sessions/{sessionId}` | Get a training session | Any |
| GET | `/closeout/training-sessions` | List training sessions | Any |
| POST | `/closeout/training-sessions/{sessionId}/reschedule` | Reschedule a session (OCC; at most two reschedules) | GCProjectManager |
| POST | `/closeout/training-sessions/{sessionId}/conduct` | Record a conducted session (`SCHEDULED` → `CONDUCTED`) | GCProjectManager |
| POST | `/closeout/retainage-releases` | Request a retainage release (server-computed amount; OCC on project) | GCProjectManager |
| GET | `/closeout/retainage-releases/{releaseId}` | Get a retainage release | Any |
| GET | `/closeout/retainage-releases` | List retainage releases | Any |
| POST | `/closeout/retainage-releases/{releaseId}/approve` | Approve a release (`REQUESTED` → `PAID`); money moves | OwnerRep |
| POST | `/closeout/retainage-releases/{releaseId}/void` | Void a `REQUESTED` release, or claw back a `PAID` one | GCProjectManager |
| POST | `/closeout/warranty-cases` | Report a warranty callback on a closed project | OwnerRep |
| GET | `/closeout/warranty-cases/{caseId}` | Get a warranty case | Any |
| GET | `/closeout/warranty-cases` | List warranty cases | Any |
| POST | `/closeout/warranty-cases/{caseId}/triage` | Triage a case (`REPORTED` → `TRIAGED`); computes the SLA due instant | GCProjectManager |
| POST | `/closeout/warranty-cases/{caseId}/resolve` | Resolve a case (`TRIAGED` → `RESOLVED`) | GCProjectManager |
| POST | `/closeout/warranty-cases/{caseId}/deny` | Deny a case (`REPORTED`/`TRIAGED` → `DENIED`) | GCProjectManager |
| POST | `/closeout/_clock/set_current_utc` | Advance the server's logical clock | GCProjectManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is an index of identifiers to statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESPONSIBLE_PARTY` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_VERIFICATION_ESCALATED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_NOT_CLOSED` | 409 Conflict |
| `ERR_OPEN_LIFE_SAFETY_ITEMS` | 409 Conflict |
| `ERR_OPEN_MAJOR_ITEMS` | 409 Conflict |
| `ERR_TOO_MANY_OPEN_MINOR_ITEMS` | 409 Conflict |
| `ERR_WALK_INCOMPLETE` | 409 Conflict |
| `ERR_NO_TRADE_PACKAGES` | 409 Conflict |
| `ERR_WALK_OVERLAP` | 409 Conflict |
| `ERR_WALK_NOT_STARTED` | 409 Conflict |
| `ERR_SCHEDULED_IN_PAST` | 409 Conflict |
| `ERR_SESSION_ROOM_CONFLICT` | 409 Conflict |
| `ERR_SESSION_NOT_STARTED` | 409 Conflict |
| `ERR_NO_ATTENDEES` | 409 Conflict |
| `ERR_RESCHEDULE_LIMIT` | 409 Conflict |
| `ERR_DUPLICATE_TRADE` | 409 Conflict |
| `ERR_DOC_ALREADY_PENDING` | 409 Conflict |
| `ERR_DOC_TYPE_ALREADY_SATISFIED` | 409 Conflict |
| `ERR_WAIVER_NOT_ACCEPTABLE_STATE` | 409 Conflict |
| `ERR_WAIVER_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_OCCUPANCY_NOT_REGISTERED` | 409 Conflict |
| `ERR_OCCUPANCY_ALREADY_REGISTERED` | 409 Conflict |
| `ERR_OCCUPANCY_BEFORE_SC` | 422 Unprocessable Entity |
| `ERR_RELEASE_KIND_ALREADY_USED` | 409 Conflict |
| `ERR_RELEASE_AMOUNT_ZERO` | 409 Conflict |
| `ERR_FINAL_RELEASE_NOT_PAID` | 409 Conflict |
| `ERR_TRADE_NOT_IN_PROJECT` | 422 Unprocessable Entity |
| `ERR_WALK_NOT_IN_PROJECT` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
