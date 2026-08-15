# Surgical Loaner Ops API — Product Requirements Document

## 1. Introduction

Every surgical day, instrument vendors deliver loaner trays that the hospital does not own but cannot operate without. Trays arrive against a case-linked deadline, must be counted and documented at the dock, sterilized in time for the scheduled incision, staged by the circulator, and — once the case is over — counted again on the way out so that shortages and damage can be charged back to the responsible party. Today this chain runs on phone calls, paper count sheets, and goodwill. The Surgical Loaner Ops API replaces that with a single system of record for the OR vendor management office: vendors and their penalty contracts, representative credentialing, loaner requests and trays, delivery check-ins, sterilization turns, OR access passes, post-case pickups, damage and loss claims, late-delivery penalties, and the escalations that bind them together.

Two ideas organize the whole design. First, posture drives gating: every loaner request carries a derived readiness that is recomputed from the live state of its trays and their sterilization projections, and that posture decides whether a case may start cleanly, must be forced with an explicit override, or triggers an automatic escalation during the final twenty-four hours before incision. Second, money follows evidence: late deliveries accrue penalties from the vendor's contractual terms, final case-delay attribution converts recorded delay events into a surcharge, and reconciliation shortages convert into claims whose vendor share is adjudicated under optimistic concurrency control with a complete audit trail. Segregation of duties keeps the coordinator who verified a count sheet from also settling the money that count sheet generates.

All operations are served under the `/vendor-office` mount and evaluated against a logical, test-drivable clock — never the wall clock — so that credential expiry, sterilization cycle completion, and access-window expiry are deterministic. The consistency model is immediate: every mutation's effects, including all cascades and rollups described in this document, are visible in the same response that performs the mutation; there is no asynchronous reconciliation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Beyond authentication, each operation is restricted to designated roles; an authenticated caller whose role is not on an operation's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five operational roles, spelled exactly as follows:

- `VendorCoordinator` — the OR vendor management office staff: vendor and representative administration, request approval, check-in verification, escalations, access decisions, pickup reconciliation, and all claims and penalty adjudication. This role also exclusively drives the logical clock.
- `ORScheduler` — the OR scheduling office: rooms, surgical cases and their lifecycle, loaner request drafting, submission and cancellation, and delay-event recording.
- `SterileProcessingTech` — the sterile processing department: sterilizer units and every sterilization turn action.
- `ORCirculatorNurse` — the OR circulator: stages trays for cases, admits credentialed representatives at the door, and records intra-operative delay events.
- `VendorRep` — a vendor representative: delivers trays through check-in, picks trays up after the case, requests OR access, and disputes pickups and claims on the vendor's behalf.

A sixth pseudo-role, `Any`, denotes that every authenticated role may use the read operations; all list and single-resource retrieval endpoints are available to any of the five roles above.

Role identity is bound to `X-User-ID` as follows. When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting `VendorRep` entity; ownership checks on any resource that references a `VendorRep` compare the resource's rep field to `X-User-ID` — so a rep calling a vendor-side operation is recorded as that rep (for example, into `rep_id` on a check-in or pickup) and is authorized only for the vendor that employs them. When `X-User-Role` is `VendorCoordinator`, `ORScheduler`, `SterileProcessingTech`, `ORCirculatorNurse`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `verified_by_user_id` on a check-in or `reconciled_by_user_id` on a pickup, where it anchors segregation of duties) but never compares it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The one exception is the claims list: claims are ordered deterministically by `created_at` ascending and then by `claim_seq` ascending — the claim `id` is never used for ordering.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Immediate Consistency

Every primary resource in the system — vendors, representatives, rooms, sterilizer units, cases, loaner requests, trays, sterilization turns, escalations, access passes, pickups, claims, and penalties — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every modification to the resource, and anchors optimistic concurrency control where that mechanism applies.

Two resources are deliberately lighter. A `CaseDelayEvent` and a `CheckInEvent` are event records: each carries `id` and `created_at` only, and both `updated_at` and `version` are absent from them. A delay event in particular is append-only — once recorded it never transitions and is never edited.

Every mutation is committed immediately and atomically with its cascades. When an operation touches several resources — for example a case completion cascading across trays, requests, and rollups — the response reflects all of those effects at once, and any subsequent read observes them.

### 2.5. The Logical Clock and Scheduled State Sweeps

The server runs on a logical clock rather than the wall clock. Before any clock call has been made, the current time is exactly 2026-08-01T00:00:00Z. A `VendorCoordinator` advances the clock through an admin-only, test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`; this document refers to that operation as the clock sweep or clock advance.

Every clock advance is also a state sweep. In the same operation that sets the new time, the system walks the time-driven transitions: a representative whose credential is `ACTIVE` but whose `credential_expires_at` has been reached or passed by the new time moves to `EXPIRED`; an access pass still `APPROVED` whose window has fully elapsed moves to `EXPIRED`, while one already `ADMITTED` moves to `EXITED`; and a sterilization turn in `STERILIZING` whose cycle has completed — that is, whose `cycle_started_at` plus the assigned unit's `cycle_minutes` falls at or before the new time — moves to `COOLDOWN` with its `cycle_completed_at` stamped as exactly `cycle_started_at` plus the unit's `cycle_minutes`. All datetimes throughout the system are exact to the second.

### 2.6. Validation Order of Precedence

When several rules could reject the same request, the server evaluates them in a fixed global order, and the caller receives the error from the first failing tier. The tiers, from first to last, are:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Body well-formedness** — the request body parses, contains every required field, and every field has a valid type and, where enumerated, a valid enum member, else `ERR_VALIDATION` (400). This tier also rejects non-positive numbers where a positive value is required and an inverted case window whose `scheduled_start_at` is not earlier than its `scheduled_end_at`.
3. **Role authorization** — the caller's role is on the endpoint's authorized list, else `ERR_FORBIDDEN_ROLE` (403).
4. **Existence** — every referenced resource exists, validated left-to-right, else the matching `ERR_{RESOURCE}_NOT_FOUND` (404).
5. **Stale-version concurrency** — where an operation carries an expected-version field, it must equal the entity's current `version`, else `ERR_STALE_VERSION` (412).
6. **State guards** — the target entity is in a state that permits the invoked transition, else the per-entity state error (the `ERR_{ENTITY}_INVALID_STATE` family, `ERR_VENDOR_NOT_ACTIVE`, `ERR_CASE_READINESS_BLOCKED`, `ERR_VENDOR_HAS_OPEN_WORK`) at 409.
7. **Credentialing and sterility safety** — an acting rep's credential is `ACTIVE` and the rep belongs to the vendor being acted for; an implant tray is never checked in without its implant log; decontamination minimums and cooldowns have elapsed; a credential outlives the case it supports. These raise `ERR_REP_CREDENTIAL_NOT_ACTIVE` (409), `ERR_IMPLANT_LOG_REQUIRED` (422), `ERR_DECON_MIN_NOT_ELAPSED` (409), `ERR_COOLDOWN_NOT_ELAPSED` (409), or `ERR_CREDENTIAL_WINDOW_INSUFFICIENT` (409).
8. **Temporal windows** — room buffered-overlap, access admit window, submit-deadline feasibility, and credential expiry in the future, raising `ERR_ROOM_TIME_CONFLICT` (409), `ERR_ACCESS_WINDOW_CLOSED` (409), `ERR_REQUEST_DEADLINE_INFEASIBLE` (422), or `ERR_CREDENTIAL_EXPIRY_PAST` (422).
9. **Constraint satisfaction** — uniqueness of codes and lines, sterilizer slot capacity, segregation of duties, the at-least-one-tray rule, and escalation-resolution linkage, raising the duplicate-code and duplicate-line errors (409), `ERR_STERILIZER_CAPACITY_EXCEEDED` (409), `ERR_SEGREGATION_OF_DUTIES` (403), `ERR_REQUEST_NO_TRAYS` (409), or `ERR_ESCALATION_RESOLUTION_INVALID` (409).
10. **Cross-entity referential coherence** — the acting rep belongs to the request's or claim's vendor, line trays belong to the path request, a delay event's linked request belongs to the case, a claim's tray and request agree, and an escalation's linked tray belongs to its request, raising `ERR_REP_VENDOR_MISMATCH` (403), `ERR_TRAY_NOT_IN_REQUEST` (422), `ERR_DELAY_REQUEST_LINK` (422), or `ERR_DELAY_EVENT_INVALID` (422).
11. **Fiscal bounds** — claim amounts, apportion percentages, waiver and settlement amounts, pickup counts, and delay attribution totals stay within their declared bounds, raising the fiscal errors documented in §3.8, §3.9, and §3.7 (all 422).

Within a tier, the per-endpoint trigger conditions are narrated in §3 alongside the workflows they guard.

### 2.7. Money, Minutes, and Rounding Discipline

All monetary amounts in this system are integer cents — never floats, never strings — and all division of money rounds half up to the nearest cent. This applies to provisional and final claim shares and to per-line shortage claims alike.

Billable penalty time uses ceiling semantics: the number of billable hours in a penalty is the billable minutes divided by sixty, rounded up to the next whole hour, so that one billable minute already bills a full hour. The per-assessment cap is applied after the rate multiplication, and it is applied separately to the time charge and to the delay surcharge — the two components are each capped on their own before they are summed.

Durations and delays are tracked in whole minutes, with negative results floored at zero. Datetimes are exact to the second. Comparisons that decide whether a sterilization projection is on time are inclusive: a projection landing exactly at its deadline counts as on time. Access windows are half-open — the lower bound is inclusive and the upper bound exclusive.

### 2.8. Vendor Exposure Rollups

Each vendor carries two live financial rollups, both starting at zero when the vendor is created and both denominated in integer cents.

`outstanding_penalty_cents` is the sum of `outstanding_cents` over exactly that vendor's penalty assessments whose status is `ASSESSED`. Penalties still `ACCRUING`, already `SETTLED`, closed as `WAIVED_CLOSED`, or annulled as `VOID` contribute nothing.

`outstanding_liability_cents` is the sum of `final_vendor_share_cents` over exactly that vendor's damage and loss claims whose status is `APPORTIONED`. Claims still `FILED`, under `DISPUTED`, or `SETTLED` contribute nothing.

The rollups move in lockstep with the underlying records: assessing a penalty adds its outstanding amount, waiving or settling subtracts the moved amount, voiding removes nothing because accruing penalties never counted, and apportioning, disputing, or settling a claim adds or removes its final vendor share. A single vendor retrieval therefore always shows the vendor's current exposure, and each movement is reflected in the same response as the operation that caused it.

### 2.9. Optimistic Concurrency Control

Two write operations in the system supersede legitimately newer derived state when driven from a stale read, and these two — and only these two — are guarded by optimistic concurrency control.

Rescheduling a case is the first. A reschedule request must carry `expected_case_version` equal to the case's current `version`. Because a new schedule re-derives delivery deadlines, sterilization windows, readiness, and access-pass windows, a client writing from an older observed version would silently overwrite fresher derived state; if the case's version has advanced since that observation, the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412).

Apportioning a damage or loss claim is the second. An apportion request must carry `expected_claim_version` equal to the claim's current `version`. Apportionment legitimately supersedes a prior apportionment — for example re-adjudication after a dispute — and moves money on the vendor's liability rollup, so a stale writer would double-move the rollup; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. All other writes are accepted or rejected purely on the validation tiers of §2.6.

### 2.10. Nested Resources and Left-to-Right Existence Validation

Many resources live under others: trays, check-ins, escalations, and pickups under a loaner request; turns and claims under a tray; delay events under a case; representatives under a vendor — the representative-registration path carries its parent vendor identifier as `vendorId`, distinct from the `{id}` placeholder used everywhere else. For any request whose path chains identifiers, the server validates existence strictly left-to-right in path-template order and rejects with the `404` error of the first identifier that does not resolve — `ERR_VENDOR_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_TRAY_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`, `ERR_TURN_NOT_FOUND`, `ERR_ESCALATION_NOT_FOUND`, `ERR_PASS_NOT_FOUND`, `ERR_PICKUP_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PENALTY_NOT_FOUND`, `ERR_DELAY_EVENT_NOT_FOUND`, `ERR_REP_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, or `ERR_STERILIZER_NOT_FOUND` — before examining anything further down the chain. Identifiers referenced inside a request body are existence-checked after the path, in the body's declared field order. A nested child that exists but belongs to a different parent is not a 404; it is the referential-integrity failure of tier 10, reported as `ERR_TRAY_NOT_IN_REQUEST` or the matching cross-link error described in §3.

### 2.11. Segregation of Duties Between Verification and Settlement

The office separates the act of verifying what was delivered from the act of settling what is owed. When a `VendorCoordinator` verifies a check-in, the verifier's `X-User-ID` is stamped onto the check-in as `verified_by_user_id`. That same identifier is thereafter barred from two settlement operations on the same request: reconciling any pickup of that request, and waiving any amount on the penalty that the check-in's late delivery created. Either attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rule is per-request and per-person: a different coordinator may reconcile and waive freely, and the barred coordinator remains free to act on every other request.

## 3. Business Logic & Workflows

### 3.1. Vendor Onboarding, Contract Terms, and Standing

A `VendorCoordinator` onboards each instrument vendor by registering its legal `vendor_name` together with a unique `vendor_code`; a code already present on any other vendor is rejected with `ERR_DUPLICATE_VENDOR_CODE` (409). The creation payload also fixes the vendor's late-delivery contract: `late_grace_minutes`, the number of grace minutes subtracted from any lateness before billing, which defaults to 15 when omitted and may never be negative; `late_rate_per_hour_cents`, the penalty rate per billable hour, which must be greater than zero; `late_penalty_cap_cents`, the per-assessment cap applied separately to the time charge and to the delay surcharge, which must be greater than zero; and `delay_surcharge_per_minute_cents`, the surcharge rate per minute of vendor-attributable case delay, which defaults to 0 and may never be negative. New vendors begin `ACTIVE` with both rollups, `outstanding_penalty_cents` and `outstanding_liability_cents`, initialized to zero.

Standing is managed through three actions. Suspending moves a vendor from `ACTIVE` to `SUSPENDED`; a suspended vendor blocks both the creation of new loaner requests and the approval of access passes, each failing with `ERR_VENDOR_NOT_ACTIVE` (409). Reinstating returns a `SUSPENDED` vendor to `ACTIVE`. Termination is terminal in both directions — from `ACTIVE` or from `SUSPENDED` the vendor moves to `TERMINATED` — but only when the vendor has no open work: no loaner request of the vendor in `DRAFT`, `SUBMITTED`, or `APPROVED`, no penalty assessment in `ACCRUING` or `ASSESSED`, and no damage or loss claim in `FILED`, `APPORTIONED`, or `DISPUTED`. Any open item rejects the termination with `ERR_VENDOR_HAS_OPEN_WORK` (409). The vendor roster can be listed with a `status` filter, and a single vendor retrieval always includes both outstanding rollups.

### 3.2. Representative Credentialing and OR Access Privileges

Vendors work on site through their representatives. A `VendorCoordinator` registers a rep under an existing vendor with `full_name`, `rep_email`, and a `credential_doc_ref` pointing at the credentialing documentation bundle; the rep's `vendor_id` is taken from the vendor named in the path. New representatives begin with `credential_status` `PENDING_VERIFICATION`.

Credential approval moves a rep from `PENDING_VERIFICATION` to `ACTIVE`, and the same approval action also serves as the credential cycle: from `EXPIRED` back to `ACTIVE` as a renewal, and from `ACTIVE` to `ACTIVE` as an extension. In every case the coordinator supplies a `credential_expires_at` that must lie strictly after the current clock time — an expiry at or before now is rejected with `ERR_CREDENTIAL_EXPIRY_PAST` (422) — and an `or_access_level` of `NONE`, `OBSERVER`, or `SCRUB_ASSIST`; both values are stamped onto the rep, and the rep's `version` increments. Independently of any manual action, the clock sweep expires credentials: a rep whose `credential_expires_at` has been reached or passed moves from `ACTIVE` to `EXPIRED` automatically.

Revocation is the terminal exit. A rep in `PENDING_VERIFICATION`, `ACTIVE`, or `EXPIRED` may be revoked to `REVOKED`, and revocation cascades into the rep's access passes: every pass still `REQUESTED` is denied with `denial_reason` recorded as `credential_revoked`, and every pass already `APPROVED` is revoked to `REVOKED`. A rep whose credential is not `ACTIVE` may not perform vendor-side delivery or pickup actions — such attempts fail with `ERR_REP_CREDENTIAL_NOT_ACTIVE` (409) — and a rep acting for a vendor other than their own employer fails with `ERR_REP_VENDOR_MISMATCH` (403). The rep roster can be filtered by `vendor_id` or by `credential_status`.

### 3.3. Rooms, Sterilizer Units, and the Case Schedule

Before cases can be scheduled, the facility side of the model is built. An `ORScheduler` registers each operating room with a `room_name` and a `turnover_buffer_minutes` — the required gap between consecutive cases in that room — which defaults to 30 minutes and may never be negative. A `SterileProcessingTech` registers each sterilizer unit with a `unit_name`, a `slot_capacity` (the maximum number of turns that may be in `STERILIZING` on the unit at once, at least 1), a `cycle_minutes` duration (greater than zero), and a `cooldown_minutes` duration (zero or more).

With rooms in place, the scheduler creates surgical cases. Each case carries a unique `case_number` — duplicates are rejected with `ERR_DUPLICATE_CASE_NUMBER` (409) — the `or_room_id` of the room it occupies, the `procedure_type`, the `surgeon_name`, and a scheduled window from `scheduled_start_at` to `scheduled_end_at`. The window must be internally consistent, with the start earlier than the end; an inverted window is rejected at intake with `ERR_VALIDATION` (400). The window must also fit the room under buffered half-open semantics: two cases in the same room coexist without conflict only when one begins at or after the other's scheduled end plus the room's `turnover_buffer_minutes`, and only cases that still occupy the room — those `SCHEDULED` or `IN_PROGRESS` — participate in the check. A colliding window is rejected with `ERR_ROOM_TIME_CONFLICT` (409). New cases begin `SCHEDULED`, with `actual_start_at` and `actual_end_at` null, `delay_minutes_provisional` and `vendor_delay_minutes_provisional` at 0, and `vendor_delay_minutes_final` null until completion. The case list can be filtered by `or_room_id` or `status`.

Rescheduling is the OCC-guarded write described in §2.9: the request carries the new `scheduled_start_at` and `scheduled_end_at` plus `expected_case_version`, the room-conflict check is re-run against the new window, and a version that no longer matches is rejected with `ERR_STALE_VERSION` (412). A successful reschedule is never a local edit. The case's `version` increments by one, and the new schedule re-derives everything pinned to it: each linked loaner request in `APPROVED` has its `required_delivery_by` recomputed from the new start; the trays of those requests have both `required_sterile_ready_by` and `projected_sterile_ready_at` recomputed and each linked request's readiness re-derived; whenever that re-derivation flips an `APPROVED` request into `AT_RISK` or `NOT_READY` and the new scheduled start is no more than twenty-four hours away, the system opens an escalation automatically, typed by cause; and every access pass of the case still `REQUESTED` or `APPROVED` has its `window_start_at` and `window_end_at` recomputed. Rescheduling is only meaningful for a case that has not started; the state guard rejects lifecycle violations with `ERR_CASE_INVALID_STATE` (409).

### 3.4. Loaner Requests: Drafting, Submission, and the Readiness Posture

When a case needs vendor instruments, an `ORScheduler` opens a loaner request linking the two sides: the payload names the `case_id` of the surgical case and the `vendor_id` of the supplying vendor, plus a `priority_class` of `STANDARD`, `URGENT`, or `EMERGENT`. The vendor must be `ACTIVE` — drafting against a suspended or terminated vendor fails with `ERR_VENDOR_NOT_ACTIVE` (409). The priority class selects the contractual lead time baked into every downstream deadline: forty-eight hours for `STANDARD`, twenty-four hours for `URGENT`, and twelve hours for `EMERGENT`. A new request begins as `DRAFT` with readiness `NOT_READY`, a null `required_delivery_by`, a null `submitted_at`, and a `penalty_exposure_cents` of 0.

While the request is `DRAFT` — adding to any later state is rejected with `ERR_REQUEST_INVALID_STATE` (409) — the scheduler builds its manifest tray by tray. Each tray is declared with a `tray_code` unique within its request (a repeat is rejected with `ERR_DUPLICATE_TRAY_CODE` at 409), a `declared_instrument_count` greater than zero, an `implant_flag` that defaults to false and marks trays whose implants require a log at check-in, and a `replacement_value_cents` greater than zero that later anchors shortage and damage claims. Trays begin `EXPECTED`, carry a `rework_count` of 0, null `delivered_instrument_count` and `returned_instrument_count`, a `shortage_count` of 0, and null sterilization window fields; each addition recomputes the request's readiness, which a fresh `EXPECTED` tray can only hold at `NOT_READY`. The tray list can be filtered by `request_id` or `status`.

Submitting is gated twice, and the gates are evaluated after the state guard that requires the request to be `DRAFT`. A request with no trays at all is rejected with `ERR_REQUEST_NO_TRAYS` (409). The deadline must also be feasible: the case's `scheduled_start_at` minus the current time must be at least the lead time of the request's `priority_class`, else the submission is rejected with `ERR_REQUEST_DEADLINE_INFEASIBLE` (422). A successful submit stamps `submitted_at` with the clock, moves the request to `SUBMITTED`, and increments its `version`.

Decision belongs to the `VendorCoordinator` and is expressed through a `decision` payload — `APPROVE` or `REJECT` — with an optional `reason`. Approval requires the supplying vendor to be `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`) and does real work: it computes `required_delivery_by` as the case's `scheduled_start_at` minus the priority lead time, sets every tray's `required_sterile_ready_by` to the case's start minus one hour of preparation buffer while clearing each tray's `projected_sterile_ready_at` to null, and recomputes readiness — which at this point is invariably `NOT_READY`, since every tray is still `EXPECTED`. Rejection moves the request to terminal `REJECTED`. Either way the request's `version` increments. A scheduler may also cancel a request from `DRAFT`, `SUBMITTED`, or `APPROVED`; cancellation is terminal `CANCELLED` and cascades exactly as the case-cancellation cascade does for that request: its non-terminal trays (those `EXPECTED`, `DELIVERY_PENDING`, `CHECKED_IN`, `PROCESSING`, `QUARANTINED`, or `MISSING`) move to `CANCELLED`, any of its penalties still `ACCRUING` move to `VOID`, and its escalations in `OPEN` or `ACKNOWLEDGED` resolve to `RESOLVED` with `resolution_type` `CASE_CANCELLED`; the request's `version` increments. Beyond the lifecycle operations, every request-scoped action — delivery check-in, pickup, manual escalation — first confirms the request is in a state that permits it and otherwise rejects with `ERR_REQUEST_INVALID_STATE` (409). The request list can be filtered by `case_id`, `vendor_id`, `status`, or `readiness`.

Readiness is the request's derived posture, recomputed by the system on every tray state change, every projection recompute, every check-in verification, staging, QA failure, release, reschedule, and case lifecycle cascade. The rule is a total order evaluated from the top. A request is `READY` when it has at least one tray and every tray that has not been `CANCELLED` stands in `STERILE_READY`, `STAGED`, or `IN_USE`. Failing that, it is `AT_RISK` when every non-`CANCELLED` tray sits in `DELIVERY_PENDING`, `CHECKED_IN`, or `PROCESSING`, and every tray in `CHECKED_IN` or `PROCESSING` carries a `projected_sterile_ready_at` that is not null and falls at or before its `required_sterile_ready_by`. In every other situation — a request with zero trays, any tray still `EXPECTED`, `MISSING`, or `QUARANTINED`, or any projection that is null or lands after its deadline — the posture is `NOT_READY`.

Flips are escalated. Whenever a recompute moves an `APPROVED` request into `AT_RISK` or `NOT_READY` while the case's `scheduled_start_at` is no more than twenty-four hours (1,440 minutes) from the current time, the system auto-creates an escalation in `OPEN`, typed by the underlying cause: a tray in `EXPECTED` or `MISSING` yields `MISSING_TRAY`, a tray in `QUARANTINED` yields `DOCUMENTATION`, and anything else — a late sterilization projection — yields `STERILIZATION_DELAY`. Finally, requests close themselves: when a pickup reconciliation leaves every tray of a request in a terminal state (`RECONCILED` or `CANCELLED`) and the linked case is `COMPLETED`, the request bubbles up from `APPROVED` to `CLOSED` and its `version` increments.

### 3.5. Delivery, Count-Sheet Verification, and the Late-Delivery Cascade

Delivery is a `VendorRep` action against a specific request. The rep presents a count sheet as `lines` — each line naming a `tray_id`, the `instrument_count_delivered`, and an optional free-text `condition_notes` — together with the documentation flags: `ifu_provided` for the instructions-for-use documentation, `implant_log_provided` for the implant log, which defaults to false when omitted, and a `loaner_agreement_ref` referencing the signed loaner agreement. The system stamps the check-in with the rep's identity (`rep_id` from the caller's `X-User-ID`) and `delivered_at` from the clock, and the record begins `SUBMITTED`. Every line's tray must belong to the path request — a foreign tray is rejected with `ERR_TRAY_NOT_IN_REQUEST` (422) — must still be `EXPECTED` or `MISSING` (any other state fails with `ERR_TRAY_INVALID_STATE` at 409, and a `MISSING` tray covered here is simply a backfill delivery), and may appear at most once across the lines (a repeated `tray_id` fails with `ERR_DUPLICATE_TRAY_LINE` at 409). When any line's tray carries `implant_flag`, `implant_log_provided` must be true, else the entire check-in is rejected with `ERR_IMPLANT_LOG_REQUIRED` (422). The caller's credential must be `ACTIVE` (`ERR_REP_CREDENTIAL_NOT_ACTIVE`) and the caller must belong to the request's vendor (`ERR_REP_VENDOR_MISMATCH`). Each covered tray moves from `EXPECTED` or `MISSING` to `DELIVERY_PENDING`, and the request's readiness is recomputed. Check-ins can be listed filtered by `request_id`, `rep_id`, or `status`.

Verification is the coordinator's counterpart, expressed as `line_dispositions` — one disposition per line, each either `ACCEPT` or `QUARANTINE`. The check-in must still be `SUBMITTED`, else `ERR_CHECKIN_INVALID_STATE` (409). Verification stamps `verified_by_user_id` with the coordinator's `X-User-ID` — the segregation-of-duties anchor of §2.11 — and computes `late_minutes` as the whole minutes from `required_delivery_by` to `delivered_at`, floored at zero. Each line then applies its disposition to its tray. An `ACCEPT` requires a delivered count of at least one; the tray moves from `DELIVERY_PENDING` to `CHECKED_IN`, its `delivered_instrument_count` is set from the line, and when that count falls short of the tray's `declared_instrument_count` the system auto-creates an `OPEN` escalation of type `INCOMPLETE_COUNT`. A `QUARANTINE` moves the tray from `DELIVERY_PENDING` to `QUARANTINED` and auto-creates an `OPEN` escalation of type `DOCUMENTATION`. Every disposition recomputes the request's readiness. When every line was accepted the check-in ends `VERIFIED`; when any line — including all of them — was quarantined, it ends `PARTIALLY_VERIFIED`.

Verification is also where late delivery becomes money, in a two-link cascade. Link one: if the computed `late_minutes` exceeds the vendor's `late_grace_minutes` — equivalently, whenever the time charge works out to more than zero — and no penalty assessment yet exists for the request, verification creates a `PenaltyAssessment` in `ACCRUING`. The new penalty snapshots `late_minutes` from the check-in, links back through `check_in_id` and `request_id`, and computes `billable_minutes` as the late minutes minus the grace minutes, floored at zero, and `time_charge_cents` as the vendor's `late_rate_per_hour_cents` multiplied by the billable hours — billable minutes divided by sixty, rounded up to a whole hour — with the result capped at the vendor's `late_penalty_cap_cents`; an on-time or within-grace delivery yields a zero charge and no penalty row at all. The penalty's `delay_surcharge_cents` stays 0 while it accrues, so `assessed_cents` equals the time charge for now; `waived_cents` and `settled_cents` start at zero, leaving `outstanding_cents` — always the assessed amount minus waived minus settled — equal to the assessed amount. Link two: the penalty's creation immediately recomputes the request's `penalty_exposure_cents`, the running sum of `time_charge_cents` plus `delay_surcharge_cents` over the request's penalties in `ACCRUING` or `ASSESSED`.

One more coordinator action lives on the tray itself: when an expected tray simply does not arrive, marking it missing moves it from `EXPECTED` to `MISSING` — any other starting state is rejected with `ERR_TRAY_INVALID_STATE` — auto-creates an `OPEN` escalation of type `MISSING_TRAY` with `linked_tray_id` pointing at the tray, and recomputes the request's readiness.

### 3.6. Sterile Processing: Turns, Rework, and Quarantine

A checked-in tray enters sterile processing when a `SterileProcessingTech` opens a sterilization turn on it. The tray must be `CHECKED_IN`, else `ERR_TRAY_INVALID_STATE` (409); the tray moves to `PROCESSING`, the turn begins in `DECONTAMINATING` with `decon_started_at` stamped from the clock, `sterilizer_unit_id` still null, and `attempt_number` set to one plus the count of prior turns on that tray. From this point the projection governs, and the request's readiness is recomputed.

Starting the cycle assigns the turn to a sterilizer unit named by `sterilizer_unit_id` in the payload and is valid only while the turn is `DECONTAMINATING` — any other turn state is rejected with `ERR_TURN_INVALID_STATE` (409). Two further guards apply. Decontamination must have run its minimum: the current time must be at least `decon_started_at` plus thirty minutes, else `ERR_DECON_MIN_NOT_ELAPSED` (409). The unit must have a free slot: the count of turns currently `STERILIZING` on that unit must be below its `slot_capacity`, else `ERR_STERILIZER_CAPACITY_EXCEEDED` (409). A successful start stamps `cycle_started_at` from the clock, moves the turn to `STERILIZING`, and sets the tray's `projected_sterile_ready_at` to the current time plus the unit's `cycle_minutes` plus its `cooldown_minutes`, recomputing readiness. Cycle completion is time-driven: the clock sweep moves a `STERILIZING` turn to `COOLDOWN` once `cycle_started_at` plus the unit's `cycle_minutes` has been reached, stamps `cycle_completed_at` as exactly that sum, and moves the tray's projection to `cycle_completed_at` plus the unit's `cooldown_minutes`, again recomputing readiness.

Release is the QA pass: the tech may release a turn only while it is in `COOLDOWN` — any other turn state fails with `ERR_TURN_INVALID_STATE` (409) — and only once the current time has reached `cycle_completed_at` plus the unit's `cooldown_minutes`, else `ERR_COOLDOWN_NOT_ELAPSED` (409). Release stamps `released_at`, moves the turn to terminal `RELEASED`, moves the tray to `STERILE_READY`, clears the tray's `projected_sterile_ready_at` to null — the actual release now governs — and recomputes readiness. From `STERILE_READY`, an `ORCirculatorNurse` may stage the tray for its case, moving it to `STAGED`, but only while the request's case is still `SCHEDULED`; otherwise the attempt fails with `ERR_CASE_INVALID_STATE` (409). Staging recomputes readiness.

QA failure is the rework loop. Failing QA — with an optional `reason` — is allowed only from a turn in `STERILIZING` or `COOLDOWN`, with any other turn state rejected as `ERR_TURN_INVALID_STATE` (409), and moves the turn to terminal `FAILED_QA`. What happens to the tray depends on its rework budget. The tray's `rework_count` increments by one; while the resulting count is at most two, the tray returns from `PROCESSING` to `CHECKED_IN`, its projection is recomputed because it needs a fresh turn, and readiness is recomputed with the flip-escalation rule of §3.4 in force. When the failure would push the count past two — the third QA failure — the tray instead moves from `PROCESSING` to `QUARANTINED`, an `OPEN` escalation of type `STERILIZATION_DELAY` is auto-created, and readiness is recomputed. Turns can be listed filtered by `tray_id`, `sterilizer_unit_id`, or `status`.

The projection itself follows the tray's position in the pipeline. While a tray is `CHECKED_IN` with no active turn, its `projected_sterile_ready_at` is the current time plus the thirty-minute decontamination minimum plus the shortest full cycle-plus-cooldown available anywhere — the minimum, over all registered sterilizer units, of each unit's `cycle_minutes` plus its `cooldown_minutes`. While a turn is `DECONTAMINATING`, the projection is that turn's `decon_started_at` plus the same thirty minutes plus the same shortest cycle-plus-cooldown. While a turn is `STERILIZING`, the projection is `cycle_started_at` plus the assigned unit's cycle and cooldown. While a turn is in `COOLDOWN`, it is `cycle_completed_at` plus the assigned unit's cooldown. Once a tray reaches `STERILE_READY` or any later state, the projection is null and the actual release governs. If no sterilizer unit exists at all, a projection that would need the fleet minimum is null, and the tray counts as not projected on time for readiness purposes. Every on-time comparison is inclusive — a projection landing exactly at `required_sterile_ready_by` is on time — and that deadline itself is always the case's `scheduled_start_at` minus the one-hour preparation buffer, recomputed whenever the case is rescheduled.

### 3.7. Case Day: Access Passes, the Start Gate, Delay Attribution, and Completion

A vendor rep who must physically support a case needs an OR access pass. The pass is requested with a `rep_id` and a `case_id`; a `VendorRep` caller may only request a pass for themselves, so the payload's `rep_id` must equal the caller's `X-User-ID` — anything else is `ERR_REP_VENDOR_MISMATCH` (403) — while a `VendorCoordinator` may file for any rep. The case must be `SCHEDULED`, else `ERR_CASE_INVALID_STATE` (409), and the pass begins `REQUESTED` with null window fields.

The coordinator decides with a `decision` payload: `APPROVE` or `DENY`, with an optional `reason`. Only a `REQUESTED` pass can be decided, and later only an `APPROVED` pass can be admitted; acting on a pass in any other state is rejected with `ERR_PASS_INVALID_STATE` (409). Approval runs four guards in the workflow's order: the case must still be `SCHEDULED` (`ERR_CASE_INVALID_STATE`); the rep's vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`); the rep's `credential_status` must be `ACTIVE` (`ERR_REP_CREDENTIAL_NOT_ACTIVE`); and the credential must outlive the case, meaning `credential_expires_at` is strictly after the case's `scheduled_end_at` — an expiry at or before the scheduled end fails with `ERR_CREDENTIAL_WINDOW_INSUFFICIENT` (409). An approved pass computes its window: `window_start_at` is the case's `scheduled_start_at` minus two hours (120 minutes) and is inclusive, while `window_end_at` is the case's `scheduled_end_at` plus thirty minutes and is exclusive; a later reschedule recomputes both for passes still `REQUESTED` or `APPROVED`. Denial moves the pass to terminal `DENIED` and stamps `denial_reason` from the payload's `reason`.

At the door, an `ORCirculatorNurse` admits a pass that is `APPROVED`, but only while the current time sits within the half-open window — at or after `window_start_at` and strictly before `window_end_at` — else `ERR_ACCESS_WINDOW_CLOSED` (409); admission moves the pass to `ADMITTED`. From there, time takes over: the clock sweep moves an `ADMITTED` pass to `EXITED` once the window's end has been reached, and an `APPROVED` pass that was never used moves to `EXPIRED` at the same boundary. Cascades can also end passes: a case cancellation or a credential revocation moves a `REQUESTED` pass to `DENIED` with `denial_reason` recorded as `case_cancelled` or `credential_revoked` respectively, and moves an `APPROVED` pass to `REVOKED`. Passes can be listed filtered by `rep_id`, `case_id`, or `status`.

Starting the case is the readiness gate. An `ORScheduler` may start only a `SCHEDULED` case, else `ERR_CASE_INVALID_STATE`. Every linked loaner request in `APPROVED` must then report readiness `READY`; if any does not, the start is blocked with `ERR_CASE_READINESS_BLOCKED` (409) unless the caller forces it with `override_readiness` set to true and a non-empty `override_reason`. A successful start stamps `actual_start_at` from the clock, computes `delay_minutes_provisional` as the whole minutes by which the actual start passed the scheduled start (never below zero), and applies the all-or-nothing provisional attribution: `vendor_delay_minutes_provisional` equals the full provisional delay when the override was used, and 0 otherwise. Trays of linked requests that stood `STAGED` move to `IN_USE`. When the override was used, the system opens one `OPEN` escalation per non-`READY` `APPROVED` request, typed by cause — `MISSING_TRAY` if any of its trays is `EXPECTED` or `MISSING`, else `DOCUMENTATION` if any is `QUARANTINED`, else `STERILIZATION_DELAY`. The case's `version` increments by one.

While the case runs — and afterwards — delay is recorded as evidence. An `ORScheduler` or `ORCirculatorNurse` records a delay event with a `cause` of `VENDOR_LATE_DELIVERY`, `STERILIZATION_TURNAROUND`, `REP_ACCESS_ISSUE`, `PATIENT`, `STAFFING`, or `OTHER`, and a `minutes` value that must be greater than zero, else `ERR_DELAY_EVENT_INVALID` (422). The case must be `IN_PROGRESS` or `COMPLETED` — any other state also fails with `ERR_DELAY_EVENT_INVALID`. For the three vendor-attributable causes (`VENDOR_LATE_DELIVERY`, `STERILIZATION_TURNAROUND`, `REP_ACCESS_ISSUE`) the event must name an `attributable_request_id`, and that request must be one of this case's own loaner requests; a missing or foreign link fails with `ERR_DELAY_REQUEST_LINK` (422). For `PATIENT`, `STAFFING`, and `OTHER` the `attributable_request_id` must be omitted. Attribution is capped: after inserting the event, the sum of `minutes` over all vendor-cause events of the case must not exceed the case's `delay_minutes_provisional`, else the recording is rejected with `ERR_CASE_DELAY_OVERATTRIBUTED` (422). The recorder's role is stamped as `recorded_by_role`. Events are append-only — they carry no `updated_at` and no `version` — and can be listed filtered by `case_id` or `attributable_request_id`.

Completion finalizes both the record and the trays. Completing an `IN_PROGRESS` case stamps `actual_end_at` and computes the final vendor attribution: if at least one delay event exists, `vendor_delay_minutes_final` is the sum of `minutes` over the vendor-cause events — `VENDOR_LATE_DELIVERY`, `STERILIZATION_TURNAROUND`, and `REP_ACCESS_ISSUE` — capped at `delay_minutes_provisional`; if no events exist at all, it inherits `vendor_delay_minutes_provisional`. Completion then cascades across every tray of every linked request: trays `IN_USE` move through `USED` to `AWAITING_PICKUP` in the same cascade; trays still `CHECKED_IN`, `PROCESSING`, `STERILE_READY`, `STAGED`, or `QUARANTINED` move straight to `AWAITING_PICKUP` — a quarantined tray is simply returned to the vendor; and trays that never materialized — `EXPECTED`, `MISSING`, or `DELIVERY_PENDING` — move to `CANCELLED`. Every tray mutation recomputes its owning request's readiness, and the case's `version` increments by one.

Cancellation is the other terminal exit, available only from `SCHEDULED` and guarded by `ERR_CASE_INVALID_STATE`. Its cascade is total: linked loaner requests in `DRAFT`, `SUBMITTED`, or `APPROVED` move to `CANCELLED`; their non-terminal trays — `EXPECTED`, `DELIVERY_PENDING`, `CHECKED_IN`, `PROCESSING`, `QUARANTINED`, or `MISSING` — move to `CANCELLED` as well; penalty assessments of those requests still `ACCRUING` move to `VOID`; access passes of the case still `REQUESTED` are `DENIED` with `denial_reason` `case_cancelled`, and those `APPROVED` are `REVOKED`; and escalations of those requests in `OPEN` or `ACKNOWLEDGED` resolve with `resolution_type` `CASE_CANCELLED`. In-flight sterilization turns are deliberately left untouched by cancellation — a turn exits `DECONTAMINATING`, `STERILIZING`, or `COOLDOWN` only through its own actions. The case's `version` increments by one.

### 3.8. Pickup, Reconciliation, and Damage or Loss Claims

After the case, the vendor takes its instruments home. A `VendorRep` records a pickup against a request as a set of `lines`, each naming a `tray_id`, the `instrument_count_returned`, and a `condition` of `OK` or `DAMAGED`. The record is stamped with `picked_up_at` from the clock and `rep_id` from the caller's `X-User-ID`, and begins `SUBMITTED`. Every line's tray must belong to the path request (`ERR_TRAY_NOT_IN_REQUEST` at 422 otherwise) and must be `AWAITING_PICKUP`, else `ERR_TRAY_INVALID_STATE` (409); a line may not return more instruments than were verified at check-in — `instrument_count_returned` greater than the tray's `delivered_instrument_count` fails with `ERR_PICKUP_COUNT_EXCEEDS_DELIVERED` (422). The caller's credential must be `ACTIVE` and the caller must belong to the request's vendor, under the same `ERR_REP_CREDENTIAL_NOT_ACTIVE` and `ERR_REP_VENDOR_MISMATCH` guards as delivery. Each covered tray moves from `AWAITING_PICKUP` to `PICKED_UP` and its `returned_instrument_count` is set from the line. Before reconciliation, the vendor's rep may dispute the pickup — moving it from `SUBMITTED` to `DISPUTED`, with an optional `reason` — provided the caller is a rep of the request's vendor, else `ERR_REP_VENDOR_MISMATCH`. Pickups can be listed filtered by `request_id`, `rep_id`, or `status`.

Reconciliation is the coordinator's settlement of the count sheet, and it is where segregation of duties bites: the pickup must be `SUBMITTED` or `DISPUTED` (else `ERR_PICKUP_INVALID_STATE` at 409), and the reconciling coordinator's `X-User-ID` must differ from the `verified_by_user_id` of every `VERIFIED` or `PARTIALLY_VERIFIED` check-in on the same request, else `ERR_SEGREGATION_OF_DUTIES` (403). A successful reconcile stamps `reconciled_by_user_id`, then works line by line. Each tray's `shortage_count` is computed as its `delivered_instrument_count` minus its `returned_instrument_count`, and the tray moves from `PICKED_UP` to terminal `RECONCILED`. Two kinds of automatic claims are filed from these lines, and the rounding order is pinned: each line is valued and rounded first, and the request-level claimed total is the sum of the per-line amounts — converting the total shortage and rounding once is non-conformant. A line whose `shortage_count` is greater than zero auto-creates a claim in `FILED` with `damage_type` `LOSS`, whose `claimed_amount_cents` is the tray's `replacement_value_cents` multiplied by the shortage and divided by the tray's `declared_instrument_count`, rounded half up to whole cents. A line whose `condition` is `DAMAGED` auto-creates a separate claim in `FILED` with `damage_type` `DAMAGE`, a `claimed_amount_cents` equal to the tray's full `replacement_value_cents`, and a `shortage_count` of 0; a line can therefore generate both. The pickup's `discrepancy_count` counts its lines that have a shortage greater than zero or a `DAMAGED` condition. Auto-created claims carry a null `pickup_id` in responses — they are discovered through the claims list filtered by `request_id`. Reconciliation finishes with the bubble-up check of §3.4: when every tray of the request is terminal and the case is `COMPLETED`, the request closes.

Claims can also be filed manually by a `VendorCoordinator`, naming the `tray_id` the claim is filed against, the `request_id` — which must agree with the tray's own request, since the claim's request linkage is denormalized from its tray — a `damage_type` of `LOSS`, `DAMAGE`, or `CONTAMINATION`, and a `claimed_amount_cents` that must be greater than zero. A non-positive amount, or a claim against a tray that is not in a claim-eligible state — the tray must be `PICKED_UP`, `RECONCILED`, or `QUARANTINED` — is rejected with `ERR_CLAIM_AMOUNT_INVALID` (422). Manual claims carry a null `pickup_id` and a `shortage_count` of 0. Every claim, manual or automatic, receives a `claim_seq` — its 1-based creation order within its request — and a presumptive vendor share computed at filing: `provisional_vendor_share_cents` is the full claimed amount for a `LOSS`, half the claimed amount rounded half up for a `DAMAGE`, and zero for a `CONTAMINATION`. Claims begin `FILED` with `final_vendor_share_cents` and `final_hospital_share_cents` null until apportionment, and the claims list is ordered by `created_at` then `claim_seq` and can be filtered by `tray_id`, `request_id`, `pickup_id`, or `status`.

Adjudication turns the presumption into a decision. Apportioning is the OCC-guarded write of §2.9: the payload carries a `vendor_share_percent` and an `expected_claim_version` equal to the claim's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (412). The percent must lie between 0 and 100 inclusive, else `ERR_CLAIM_APPORTION_INVALID` (422). Apportionment moves a claim from `FILED` to `APPORTIONED`, computes `final_vendor_share_cents` as the claimed amount multiplied by the percent and divided by one hundred, rounded half up to whole cents, and sets `final_hospital_share_cents` to the remainder — the claimed amount minus the vendor share — so the two always sum to the claim. The vendor's `outstanding_liability_cents` increases by the final vendor share, and the claim's `version` increments by one. The vendor may answer through one of its reps: disputing an `APPORTIONED` claim moves it to `DISPUTED`, subtracts the final vendor share back off the liability rollup, and requires the caller to be a rep of the claim request's vendor, else `ERR_REP_VENDOR_MISMATCH`; an optional `reason` may accompany the dispute. A disputed claim can be apportioned again under the same OCC and percent guards, recomputing the final shares from the new percent and adding the new vendor share back onto the rollup — the same claim data under a different percent yields different cents than the provisional presumption. Finally, settling an `APPORTIONED` claim moves it to terminal `SETTLED` and subtracts its final vendor share from the liability rollup; a claim in any other state cannot be settled, apportioned, or disputed, and such attempts fail with `ERR_CLAIM_INVALID_STATE` (409).

### 3.9. Escalations, Penalty Settlement, and Financial Close

Escalations are the office's exception queue. Beyond the automatic creations scattered through §3.4 to §3.7, a `VendorCoordinator` may raise one manually on a request, supplying a `type` of `MISSING_TRAY`, `INCOMPLETE_COUNT`, `DOCUMENTATION`, `STERILIZATION_DELAY`, or `LATE_DELIVERY`; when the type scopes to a specific tray, the `linked_tray_id` is required, and any supplied `linked_tray_id` must reference a tray of the same request, else `ERR_TRAY_NOT_IN_REQUEST` (422). Escalations begin `OPEN`. Acknowledging moves one from `OPEN` to `ACKNOWLEDGED` — acknowledging anything else fails with `ERR_ESCALATION_INVALID_STATE` (409). Resolving moves an escalation from `OPEN` or `ACKNOWLEDGED` to terminal `RESOLVED` and stamps the payload's `resolution_type`, one of `BACKFILL_DELIVERY`, `SUBSTITUTE_APPROVED`, `CASE_RESCHEDULED`, `CASE_CANCELLED`, or `WAIVED`. One resolution guard protects the backfill story: resolving a `MISSING_TRAY` escalation with `BACKFILL_DELIVERY` requires the linked tray to have actually materialized — it must stand in `DELIVERY_PENDING`, `CHECKED_IN`, `PROCESSING`, `STERILE_READY`, `STAGED`, `IN_USE`, `USED`, `AWAITING_PICKUP`, `PICKED_UP`, or `RECONCILED`; a tray still `EXPECTED`, `MISSING`, or `CANCELLED` fails with `ERR_ESCALATION_RESOLUTION_INVALID` (409). Escalations can be listed filtered by `request_id`, `status`, `type`, or `linked_tray_id`.

Penalty settlement closes the late-delivery ledger. A penalty born at verification sits in `ACCRUING` — its delay surcharge still zero — until the case it fed is finished, because the surcharge needs the final delay attribution. Assessing requires the penalty to be `ACCRUING` (else `ERR_PENALTY_INVALID_STATE` at 409) and the penalty's request's case to be `COMPLETED` (else `ERR_CASE_INVALID_STATE` at 409). Assessment computes `delay_surcharge_cents` as the case's `vendor_delay_minutes_final` multiplied by the vendor's `delay_surcharge_per_minute_cents`, capped at the vendor's `late_penalty_cap_cents`; sets `assessed_cents` to the sum of `time_charge_cents` and `delay_surcharge_cents`; initializes `outstanding_cents` to the assessed amount; recomputes the request's `penalty_exposure_cents`; and adds the outstanding amount onto the vendor's `outstanding_penalty_cents`. The penalty is now `ASSESSED`.

From `ASSESSED`, money moves in exactly two ways. Waiving — which requires `waive_amount_cents` and a `reason` — is barred to the coordinator who verified the originating check-in, per §2.11, with violations rejected as `ERR_SEGREGATION_OF_DUTIES` (403); the waived amount may not exceed the penalty's `outstanding_cents`, else `ERR_WAIVER_EXCEEDS_OUTSTANDING` (422). A waiver adds to `waived_cents`, recomputes `outstanding_cents` as the assessed amount minus waived minus settled, and subtracts the waived amount from the vendor's `outstanding_penalty_cents`. When a waiver brings the outstanding amount to exactly zero the penalty closes as `WAIVED_CLOSED`; otherwise it remains `ASSESSED` and further partial waivers may follow under the same guards. Settling requires the `settle_amount_cents` to equal the outstanding amount exactly — anything else is `ERR_SETTLE_AMOUNT_MISMATCH` (422) — adds to `settled_cents`, zeroes `outstanding_cents`, subtracts the settled amount from the vendor rollup, and moves the penalty to terminal `SETTLED`. The remaining exit is `VOID`, which the system applies to an `ACCRUING` penalty when its request or case is cancelled; voiding recomputes the request's `penalty_exposure_cents` and never touched the vendor rollup, since accruing penalties never counted toward it. Penalties can be listed filtered by `request_id`, `check_in_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new resource — a vendor, room, sterilizer unit, case, delay event, loaner request, tray, check-in, sterilization turn, escalation, access pass, pickup, claim, or a representative under a vendor — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions, decisions, verification, reconciliation, settlement, and the clock advance — return `200 OK`. The complete request and response shapes of every operation are defined by the narratives of §2 and §3; this table is the routing and authorization index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vendor-office/_clock/set_current_utc` | Advance the logical clock and run the time-driven state sweep | VendorCoordinator |
| POST | `/vendor-office/vendors` | Create a vendor with its penalty contract terms | VendorCoordinator |
| GET | `/vendor-office/vendors` | List vendors | Any |
| GET | `/vendor-office/vendors/{id}` | Get a vendor, including outstanding rollups | Any |
| POST | `/vendor-office/vendors/{id}/suspend` | Suspend an active vendor | VendorCoordinator |
| POST | `/vendor-office/vendors/{id}/reinstate` | Reinstate a suspended vendor | VendorCoordinator |
| POST | `/vendor-office/vendors/{id}/terminate` | Terminate a vendor with no open work | VendorCoordinator |
| POST | `/vendor-office/vendors/{vendorId}/reps` | Register a representative under a vendor | VendorCoordinator |
| GET | `/vendor-office/reps` | List representatives | Any |
| GET | `/vendor-office/reps/{id}` | Get a representative | Any |
| POST | `/vendor-office/reps/{id}/approve-credential` | Grant, renew, or extend a rep credential | VendorCoordinator |
| POST | `/vendor-office/reps/{id}/revoke-credential` | Revoke a rep credential, cascading to access passes | VendorCoordinator |
| POST | `/vendor-office/or-rooms` | Create an OR room | ORScheduler |
| GET | `/vendor-office/or-rooms` | List OR rooms | Any |
| GET | `/vendor-office/or-rooms/{id}` | Get an OR room | Any |
| POST | `/vendor-office/sterilizer-units` | Create a sterilizer unit | SterileProcessingTech |
| GET | `/vendor-office/sterilizer-units` | List sterilizer units | Any |
| GET | `/vendor-office/sterilizer-units/{id}` | Get a sterilizer unit | Any |
| POST | `/vendor-office/cases` | Create a surgical case with room conflict check | ORScheduler |
| GET | `/vendor-office/cases` | List surgical cases | Any |
| GET | `/vendor-office/cases/{id}` | Get a case with delay attribution fields | Any |
| POST | `/vendor-office/cases/{id}/reschedule` | OCC-guarded reschedule re-deriving deadlines, tray windows, and pass windows | ORScheduler |
| POST | `/vendor-office/cases/{id}/start` | Start the case under the readiness gate | ORScheduler |
| POST | `/vendor-office/cases/{id}/complete` | Complete the case with final delay attribution and tray cascade | ORScheduler |
| POST | `/vendor-office/cases/{id}/cancel` | Cancel the case with full cascade | ORScheduler |
| POST | `/vendor-office/cases/{id}/delay-events` | Record a delay event on the case | ORScheduler, ORCirculatorNurse |
| GET | `/vendor-office/delay-events` | List delay events | Any |
| GET | `/vendor-office/delay-events/{id}` | Get a delay event | Any |
| POST | `/vendor-office/requests` | Create a draft loaner request linking case and vendor | ORScheduler |
| GET | `/vendor-office/requests` | List loaner requests | Any |
| GET | `/vendor-office/requests/{id}` | Get a loaner request | Any |
| POST | `/vendor-office/requests/{id}/trays` | Add a tray to a draft request | ORScheduler |
| GET | `/vendor-office/requests/{id}/trays` | List trays of a request | Any |
| POST | `/vendor-office/requests/{id}/submit` | Submit a draft request | ORScheduler |
| POST | `/vendor-office/requests/{id}/decide` | Approve or reject a submitted request | VendorCoordinator |
| POST | `/vendor-office/requests/{id}/cancel` | Cancel a request with cascade | ORScheduler |
| GET | `/vendor-office/trays` | List trays | Any |
| GET | `/vendor-office/trays/{id}` | Get a tray | Any |
| POST | `/vendor-office/trays/{id}/mark-missing` | Mark an expected tray missing | VendorCoordinator |
| POST | `/vendor-office/trays/{id}/stage` | Stage a sterile-ready tray for its case | ORCirculatorNurse |
| POST | `/vendor-office/requests/{id}/check-ins` | Vendor delivery check-in with count sheet and documentation | VendorRep |
| GET | `/vendor-office/check-ins` | List check-ins | Any |
| GET | `/vendor-office/check-ins/{id}` | Get a check-in | Any |
| POST | `/vendor-office/check-ins/{id}/verify` | Verify a check-in with per-line dispositions | VendorCoordinator |
| POST | `/vendor-office/trays/{id}/turns` | Open a sterilization turn on a checked-in tray | SterileProcessingTech |
| GET | `/vendor-office/turns` | List sterilization turns | Any |
| GET | `/vendor-office/turns/{id}` | Get a sterilization turn | Any |
| POST | `/vendor-office/turns/{id}/start-cycle` | Start the sterilization cycle on a unit | SterileProcessingTech |
| POST | `/vendor-office/turns/{id}/release` | Release a cooled-down turn (QA pass) | SterileProcessingTech |
| POST | `/vendor-office/turns/{id}/fail-qa` | Fail QA, driving the tray rework loop | SterileProcessingTech |
| POST | `/vendor-office/requests/{id}/escalations` | Raise a manual escalation on a request | VendorCoordinator |
| GET | `/vendor-office/escalations` | List escalations | Any |
| GET | `/vendor-office/escalations/{id}` | Get an escalation | Any |
| POST | `/vendor-office/escalations/{id}/acknowledge` | Acknowledge an open escalation | VendorCoordinator |
| POST | `/vendor-office/escalations/{id}/resolve` | Resolve an escalation with a resolution type | VendorCoordinator |
| POST | `/vendor-office/access-passes` | Request OR access for a rep on a case | VendorRep, VendorCoordinator |
| GET | `/vendor-office/access-passes` | List access passes | Any |
| GET | `/vendor-office/access-passes/{id}` | Get an access pass | Any |
| POST | `/vendor-office/access-passes/{id}/decide` | Approve or deny an access pass | VendorCoordinator |
| POST | `/vendor-office/access-passes/{id}/admit` | Admit an approved pass within its window | ORCirculatorNurse |
| POST | `/vendor-office/requests/{id}/pickups` | Record a post-case pickup with returned counts | VendorRep |
| GET | `/vendor-office/pickups` | List pickups | Any |
| GET | `/vendor-office/pickups/{id}` | Get a pickup | Any |
| POST | `/vendor-office/pickups/{id}/reconcile` | Reconcile counts, filing automatic claims | VendorCoordinator |
| POST | `/vendor-office/pickups/{id}/dispute` | Dispute a submitted pickup | VendorRep |
| POST | `/vendor-office/claims` | File a manual damage or loss claim | VendorCoordinator |
| GET | `/vendor-office/claims` | List claims in deterministic order | Any |
| GET | `/vendor-office/claims/{id}` | Get a claim | Any |
| POST | `/vendor-office/claims/{id}/apportion` | OCC-guarded apportionment or re-apportionment of vendor share | VendorCoordinator |
| POST | `/vendor-office/claims/{id}/dispute` | Dispute an apportioned claim | VendorRep |
| POST | `/vendor-office/claims/{id}/settle` | Settle an apportioned claim | VendorCoordinator |
| GET | `/vendor-office/penalties` | List penalty assessments | Any |
| GET | `/vendor-office/penalties/{id}` | Get a penalty assessment | Any |
| POST | `/vendor-office/penalties/{id}/assess` | Assess an accruing penalty after case completion | VendorCoordinator |
| POST | `/vendor-office/penalties/{id}/waive` | Waive part or all of an assessed penalty | VendorCoordinator |
| POST | `/vendor-office/penalties/{id}/settle` | Settle exactly the outstanding amount | VendorCoordinator |

## 5. Error Code Catalogue

The trigger condition for every error below is defined in the narrative of §2 and §3 where the guarded workflow lives; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_REP_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_STERILIZER_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_TRAY_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKIN_NOT_FOUND` | 404 Not Found |
| `ERR_TURN_NOT_FOUND` | 404 Not Found |
| `ERR_ESCALATION_NOT_FOUND` | 404 Not Found |
| `ERR_PASS_NOT_FOUND` | 404 Not Found |
| `ERR_PICKUP_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_PENALTY_NOT_FOUND` | 404 Not Found |
| `ERR_DELAY_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VENDOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_VENDOR_HAS_OPEN_WORK` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_READINESS_BLOCKED` | 409 Conflict |
| `ERR_REQUEST_INVALID_STATE` | 409 Conflict |
| `ERR_TRAY_INVALID_STATE` | 409 Conflict |
| `ERR_TURN_INVALID_STATE` | 409 Conflict |
| `ERR_CHECKIN_INVALID_STATE` | 409 Conflict |
| `ERR_PICKUP_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_PENALTY_INVALID_STATE` | 409 Conflict |
| `ERR_PASS_INVALID_STATE` | 409 Conflict |
| `ERR_ESCALATION_INVALID_STATE` | 409 Conflict |
| `ERR_REP_CREDENTIAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_CREDENTIAL_EXPIRY_PAST` | 422 Unprocessable Entity |
| `ERR_CREDENTIAL_WINDOW_INSUFFICIENT` | 409 Conflict |
| `ERR_IMPLANT_LOG_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DECON_MIN_NOT_ELAPSED` | 409 Conflict |
| `ERR_COOLDOWN_NOT_ELAPSED` | 409 Conflict |
| `ERR_ROOM_TIME_CONFLICT` | 409 Conflict |
| `ERR_ACCESS_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REQUEST_DEADLINE_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VENDOR_CODE` | 409 Conflict |
| `ERR_DUPLICATE_CASE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_TRAY_CODE` | 409 Conflict |
| `ERR_DUPLICATE_TRAY_LINE` | 409 Conflict |
| `ERR_STERILIZER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_REQUEST_NO_TRAYS` | 409 Conflict |
| `ERR_ESCALATION_RESOLUTION_INVALID` | 409 Conflict |
| `ERR_REP_VENDOR_MISMATCH` | 403 Forbidden |
| `ERR_TRAY_NOT_IN_REQUEST` | 422 Unprocessable Entity |
| `ERR_DELAY_REQUEST_LINK` | 422 Unprocessable Entity |
| `ERR_DELAY_EVENT_INVALID` | 422 Unprocessable Entity |
| `ERR_CLAIM_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_CLAIM_APPORTION_INVALID` | 422 Unprocessable Entity |
| `ERR_WAIVER_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_SETTLE_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PICKUP_COUNT_EXCEEDS_DELIVERED` | 422 Unprocessable Entity |
| `ERR_CASE_DELAY_OVERATTRIBUTED` | 422 Unprocessable Entity |
