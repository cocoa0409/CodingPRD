# HOA Architectural Review API — Product Requirements Document

## 1. Introduction

Homeowners associations live and die by the consistency of their architectural review process. An owner who wants to add a room, repaint a facade, or install solar panels files an application with drawings and material samples; the architectural review committee must interpret the design guidelines and respond within a statutory deadline, because silence past that deadline is not neutrality — it is a deemed approval with the full force of a committee grant. The outcome of review is rarely a clean yes or no: approvals arrive carrying conditions, denials may be appealed to the board, and every granted deviation becomes precedent that shapes how the next application under the same guideline section must be read.

This document specifies an API that operates that entire pipeline end to end. Beyond the review itself, the platform governs the construction phase — enforcing construction windows and contractor rules, scheduling completion inspections, and driving non-compliance into a remediation path — and maintains an enforcement ladder in which violations accrue daily fines and unpaid balances escalate automatically into liens that block further submissions. All operations are served under the `/arc` mount and are executed by five acting roles whose duties are deliberately segregated: the manager who administers the pipeline, the homeowner who files and remediates, the committee member who votes, the board member who decides appeals, and the inspector who records completion results.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five roles, spelled exactly as follows: `Manager`, `Homeowner`, `CommitteeMember`, `BoardMember`, and `Inspector`. A request whose headers are missing, or whose `X-User-Role` is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not on the target operation's authorized list is rejected with `ERR_UNAUTHORIZED`.

Two of the roles are opaque operator identities. When `X-User-Role` is `Manager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same holds when `X-User-Role` is `Inspector`. The server does not compare those identifiers to any entity's `id`.

The remaining three roles are backed by the Owner registry. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting Owner, and ownership checks on any resource that references an Owner compare the resource's foreign-key field — an application's `owner_id`, or a property's `primary_owner_id` — to `X-User-ID`. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is likewise the `id` of the acting Owner; a committee member is barred from acting on an application where they are themselves the applicant. When `X-User-Role` is `BoardMember`, `X-User-ID` is again the `id` of the acting Owner; a board member is barred from deciding an appeal when they are the applicant or when they cast a committee ballot on the same application. Breaches of these segregation-of-duties rules are rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system — associations, owners, properties, applications, attachments, committee votes, appeals, permits, blackout periods, inspections, violations, fines, liens, and variances — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations performed by system-driven transitions such as sweeps and cascades.

All stamped timestamps and all date arithmetic in the system derive from the server's logical clock (see §2.6); the server never consults wall-clock time.

### 2.5. The Property Compliance Ledger

Each property maintains three derived fields that together form its compliance ledger, and the server keeps them current automatically as enforcement events occur — no client writes them directly.

- `outstanding_fine_balance_cents` is the sum, over every violation of the property in any status, of that violation's single fine's `outstanding_cents`, where a fine's `outstanding_cents` is its `accrued_cents` minus its `settled_cents` minus its `waived_cents`. Each fine's accrued figure is already an integer built from per-day rounded increments (see §2.7), so the property balance sums those integers directly; summing unrounded raw amounts and rounding once at the end is forbidden. For every fine, the invariant `accrued_cents` equals `settled_cents` plus `waived_cents` plus `outstanding_cents` holds at all times.
- `open_permit_count` is the number of construction permits in `ACTIVE` status linked, through applications, to the property. It is recomputed whenever a permit is created or completed.
- `compliance_posture` is derived in a fixed order: `LIENED` if any lien of the property is in `FILED` status; otherwise `FINES_OUTSTANDING` if `outstanding_fine_balance_cents` is greater than zero; otherwise `CLEAR`.

The balance and the posture are recomputed on any fine mutation — creation, the accrual sweep, a waiver, a settlement — and on violation remediation. This recomputation is the system's hierarchical-consistency mechanism: a mutation deep in the fine and violation layer bubbles up to the property, and the property's posture in turn gates behavior elsewhere, most notably blocking new application submissions while the property is `LIENED` (rejected with `ERR_PROPERTY_LIENED`).

### 2.6. Statutory Timekeeping and the Logical Clock

Time in this system is logical, not physical. A manager-only capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; before any such call, the clock's startup default is exactly 2026-05-01T00:00:00Z, and the server never falls back to wall-clock time. Every stamped timestamp, every deadline computation, and every accrual day boundary is evaluated against this logical clock.

Statutory review deadlines are counted in days according to the association's `counting_mode`. Under `CALENDAR` counting, every day counts. Under `BUSINESS` counting, only Monday through Friday count; Saturdays and Sundays are skipped, so for an identical submission instant the deemed-approval date lands strictly later whenever a weekend intervenes.

A manager-only daily ops checkpoint drives all time-triggered system transitions at the current logical date in a fixed order: first deemed approvals, then fine accrual, then violation escalation, then lien auto-filing, and finally permit expiry. The checkpoint is idempotent per date — re-running it for the same logical date does not double-apply any step — and reports how many transitions of each kind it applied. The detailed mechanics of each step live with their workflows in §3.5 and §3.8.

### 2.7. Monetary Precision and Fine Arithmetic

All monetary values are handled as integer numbers of cents; there are no fractional-cent amounts anywhere in the system. Escalation multipliers are expressed in basis points, where 10000 basis points is exactly 1.0x and 20000 basis points is exactly 2.0x.

Fine accrual follows a pinned rounding order: each individual day's increment is rounded half up to a whole cent (a half cent rounds up) before being added into the fine's `accrued_cents`, and the accrued total is the sum of those per-day rounded increments. The alternative ordering — summing raw unrounded per-day amounts and rounding the total once — is explicitly forbidden, because it yields different totals than the pinned order.

### 2.8. Construction Windows and Calendar Semantics

Permit construction windows are half-open intervals: the window includes its `window_start` date and excludes its `window_end` date, written [start, end). Two windows on the same property conflict when each window starts before the other ends — that is, the first window's start is earlier than the second window's end and the second window's start is earlier than the first window's end. Adjacency is allowed: when one window's end equals the other's start, the two windows do not conflict.

Blackout periods, by contrast, are closed intervals that include both their `start_date` and their `end_date`. A permit window conflicts with a blackout when the window's start is on or before the blackout's end date and the window's end is after the blackout's start date. Because the blackout's final day is inside the blackout, a window whose start equals that final day conflicts with the blackout — a deliberate asymmetry with permit-permit adjacency, where touching endpoints never conflict. Window lengths are measured as the number of whole days in the half-open interval.

### 2.9. Validation Order and Error Precedence

Every request is validated against the rules below in the listed order, and the first failing rule produces the response error. Textual mention of a rule elsewhere in this document does not change this precedence.

1. Authentication: the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role; otherwise `ERR_UNAUTHENTICATED` (401). Applies to all operations.
2. Role authorization: the acting role is in the operation's authorized roles list; otherwise `ERR_UNAUTHORIZED` (403). Applies to all operations.
3. Path existence: path template identifiers resolve to existing resources, validated left to right; the first unresolved identifier yields its specific 404 — `ERR_ASSOCIATION_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_FINE_NOT_FOUND`, `ERR_LIEN_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, or `ERR_VARIANCE_NOT_FOUND`. Applies to all operations.
4. Request body shape: required fields are present, enum fields hold declared members, and unknown fields are rejected; violations yield `ERR_INVALID_REQUEST` (400), with enum member violations yielding `ERR_INVALID_ENUM` (400). Applies to all operations.
5. Context authorization: a `Homeowner` must own the acted-on resource (the application's `owner_id` or the property's `primary_owner_id` equals `X-User-ID`), and a `CommitteeMember` or `BoardMember` must not be the applicant of the acted-on application — with the additional bar that a `BoardMember` must not have cast a committee vote on that application. Ownership failures yield `ERR_UNAUTHORIZED` (403); segregation-of-duties violations yield `ERR_SEGREGATION_OF_DUTIES` (403).
6. State: the target resource is in a state from which the requested transition is defined; otherwise `ERR_INVALID_STATE` (409). This covers terminal-state lockdown — a resource in a terminal state accepts no further transitions — and cross-entity state gates such as the re-inspection gate of §3.7. Applies to all action operations.
7. Posture gate: application submission requires the property's `compliance_posture` to be other than `LIENED`; otherwise `ERR_PROPERTY_LIENED` (409). Applies to the submission operation only.
8. Temporal checks, evaluated in this sub-order: (8a) window overlap against other `ACTIVE` permits on the same property, half-open semantics, yielding `ERR_WINDOW_OVERLAP` (409); then (8b) blackout conflict against the association's blackout calendar, closed-interval semantics, yielding `ERR_BLACKOUT_CONFLICT` (422); then (8c) appeal-window expiry, yielding `ERR_APPEAL_WINDOW_EXPIRED` (422) when the days since the denial exceed the appeal window. Checks 8a and 8b apply to the committee decision operation, the appeal decision operation, and the permit extension operation; check 8c applies to the appeal filing operation.
9. Constraint satisfaction, evaluated in this sub-order: (9a) submission completeness, yielding `ERR_INCOMPLETE_SUBMISSION` (422) when the application lacks the required attachments; (9b) window length, yielding `ERR_WINDOW_TOO_LONG` (422) when a requested or extended window exceeds the association's maximum; (9c) quorum, yielding `ERR_QUORUM_NOT_MET` (422) when too few ballots have been cast at decision time. Check 9a applies to the submission operation, 9b to application creation and permit extension, and 9c to the committee decision operation.
10. Variance precedent: the referenced application must be in `APPROVED_WITH_CONDITIONS` or `DEEMED_APPROVED`; otherwise `ERR_PRECEDENT_NOT_APPROVED` (422). Applies to variance recording.
11. Fiscal checks, evaluated in this sub-order: (11a) a settlement amount must equal the fine's outstanding amount exactly, yielding `ERR_SETTLEMENT_AMOUNT_MISMATCH` (422); (11b) a waiver amount must not exceed the fine's outstanding amount, yielding `ERR_WAIVER_EXCEEDS_OUTSTANDING` (422); (11c) a lien satisfaction requires the property balance to be zero, yielding `ERR_LIEN_BALANCE_OUTSTANDING` (409). These apply to the settle, waive, and lien-satisfy operations respectively.
12. Optimistic concurrency: an operation carrying an expected-version field requires it to equal the parent entity's current `version`; otherwise `ERR_STALE_VERSION` (412). Applies to the conditions amendment and contractor change operations only.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two carry an expected-version field.

Amending an application's approval conditions requires the request to carry `expected_application_version`, holding the application `version` the client last observed. If the application's current `version` no longer matches — because another writer has amended the conditions or otherwise legitimately advanced the application since the client's last read — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.

Changing the contractor on a construction permit likewise requires `expected_permit_version`, holding the permit `version` the client last observed. A mismatch with the permit's current `version` — for example because another writer changed the contractor or extended the window in the meantime — is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other operation accepts a version field.

### 2.11. Nested Resource Retrieval

The API enforces strict, hierarchical validation for all requests that target nested resources. When an operation path contains multiple resource identifiers (for example, an association identifier followed by a property identifier), the server validates the existence of each identifier in sequential, left-to-right order, and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve — before any later identifier, body, or business rule is examined. A request addressed to a property under a non-existent association therefore fails with `ERR_ASSOCIATION_NOT_FOUND`, and one addressed to an application under a non-existent property fails with `ERR_PROPERTY_NOT_FOUND`, regardless of what else is wrong with the request.

## 3. Business Logic & Workflows

### 3.1. Chartering the Association: Configuration, Owners, and Properties

Everything begins with a `Manager` chartering an association. The charter carries the association's legal `name` together with the full rulebook that later governs reviews, fines, and liens: `statutory_response_days` (at least 1) sets the committee's response deadline in countable days; `counting_mode` chooses `CALENDAR` or `BUSINESS` day counting; `fine_mode` selects the `SIMPLE_DAILY` or `TIERED_ESCALATION` accrual variant; `base_fine_cents` (at least 0) is the amount assessed when a violation is created; `daily_fine_cents` (at least 0) is the per-day accrual rate before escalation; `grace_days` (default 0, never negative) is the number of days charged at the base daily rate before the tier escalates; `escalation_multiplier_bp` (default 10000, and never below 10000) is the escalated-tier multiplier in basis points. The lien ladder is configured by `lien_threshold_cents` (at least 1), the property balance at or above which a lien auto-files, and `lien_min_age_days` (default 0, never negative), the minimum age of the oldest unpaid fine before a lien may file. Committee governance is set by `committee_size` (at least 1), `quorum_min` (at least 1 and at most `committee_size`), and `supermajority_required` (default true), which selects between the two tally variants of §3.4. Finally, `max_window_days` (at least 1) caps construction window length, `default_window_days` (default 90) is a reserved, informational default that no rule enforces, `remediation_days` (default 7, never negative) sets the span from violation creation to the remediation deadline, and `appeal_window_days` (default 30, at least 1) sets how long after a denial an appeal may be filed.

With the charter in place, the manager registers owners — each scoped to the association through its `association_id` — by supplying a `full_name` and a contact `email`, and registers properties by supplying the `lot_number`, the street `address`, and the `primary_owner_id` of the owner responsible for the lot. A newly registered property starts with its `compliance_posture` at `CLEAR`, its `outstanding_fine_balance_cents` at zero, and its `open_permit_count` at zero.

### 3.2. The Blackout Calendar and the Variance Precedent Registry

Two association-scoped registries shape later decisions. The first is the blackout calendar: a `Manager` declares a blackout period by supplying a `start_date`, an `end_date` that must be on or after the start date, and an optional `reason` such as a holiday moratorium. Blackouts are closed intervals per §2.8, and the full calendar is listable by any role.

The second registry tracks variance precedent. When the committee or the statute has approved a project that deviates from a guideline, a `Manager` records the precedent by supplying the `application_id` of the approved application, the `guideline_section` the variance deviates from, and a `deviation_description` of what was granted; the server stamps `recorded_at`. A variance may only reference an application whose status is `APPROVED_WITH_CONDITIONS` or `DEEMED_APPROVED`; referencing any other application is rejected with `ERR_PRECEDENT_NOT_APPROVED`. The registry is searchable by any role, with an optional `guideline_section` query filter, and the precedents referencing a particular application are also listable on that application.

### 3.3. Drafting and Submitting an Application

A `Homeowner` initiates the review pipeline by creating a draft application on a property — the new application is bound to its subject property through `property_id` — supplying the `owner_id` of the applicant, which must equal the caller's `X-User-ID`, failing which the request is rejected with `ERR_UNAUTHORIZED`, together with the `project_type` (one of `ADDITION`, `FENCE`, `PAINT`, `ROOF`, `SOLAR`, or `OTHER`), the `guideline_section` the project falls under (for example SEC-4.2), a free-text `description`, and the requested construction window as `requested_window_start` and `requested_window_end`, both ISO dates in YYYY-MM-DD form. The requested window is a half-open interval per §2.8, and its length in whole days must not exceed the association's `max_window_days`; an over-long window is rejected with `ERR_WINDOW_TOO_LONG`. A new application starts in `DRAFT` status with `decision_outcome` at `NONE`, an empty `decision_reason`, an empty `conditions` list, and `applicant_hold_days` at zero.

While the application is in `DRAFT` — and later, while it is in `REVISION_REQUESTED` — the applicant attaches the supporting artifacts, each with a `kind` of `DRAWING` or `MATERIAL_SAMPLE`, a human-readable `label` such as a north elevation, and the storage `uri` of the uploaded artifact. Attempting to attach artifacts in any other application state is rejected with `ERR_INVALID_STATE`. An application's attachments are listable by any role, optionally filtered by `kind`.

Submission moves the application from `DRAFT` to `SUBMITTED` and is where the pipeline's first gates bite. The posture gate fires first: if the property's `compliance_posture` is `LIENED`, the submission is rejected with `ERR_PROPERTY_LIENED`. Completeness is checked next: the application must carry at least one attachment of `kind` `DRAWING` and at least one of `kind` `MATERIAL_SAMPLE`, and a submission missing either is rejected with `ERR_INCOMPLETE_SUBMISSION`. A successful submission stamps `submitted_at` — this stamp is written on the first submission only and is never restamped by any later resubmission, because the statutory clock of §3.5 anchors to it — and increments the application's `version` by one. The applications of a property are listable with an optional `status` filter, and the applications filed by an owner are listable on that owner.

### 3.4. Committee Review: Ballots, Revisions, and the Decision Tally

A `Manager` opens committee review on a `SUBMITTED` application, moving it to `UNDER_REVIEW`, stamping `review_started_at`, and incrementing `version` by one. From that point until a decision lands, the committee's work is ballots and revisions.

Any `CommitteeMember` may cast a `ballot` of `APPROVE`, `DENY`, or `ABSTAIN` while the application is `UNDER_REVIEW`; casting in any other state is rejected with `ERR_INVALID_STATE`. The ballot is recorded on a vote row whose `voter_owner_id` is taken from the caller's `X-User-ID`, with `cast_at` preserving the first-cast timestamp. There is exactly one vote row per distinct voter on an application: a member who votes again recasts, replacing the existing ballot and incrementing `recast_count` — never adding a second row — so the count of `APPROVE` plus `DENY` plus `ABSTAIN` ballots always equals the number of distinct voters. A committee member who is the applicant is barred from acting on that application under §2.9's segregation-of-duties rule, surfacing as `ERR_SEGREGATION_OF_DUTIES`. The ballots of an application are listable by any role, as are the ballots cast by a particular owner.

When the committee wants changes, a `CommitteeMember` requests revisions, supplying `revision_notes`; the application moves from `UNDER_REVIEW` to `REVISION_REQUESTED`, the applicant-hold window opens, and `version` increments. The applicant — and only the applicant, with `owner_id` equal to `X-User-ID` — resubmits, cycling the application back from `REVISION_REQUESTED` to `UNDER_REVIEW`. On resubmission, `applicant_hold_days` grows by the whole days after the revision request's date up to and including the resubmission date, and `version` increments again. This revision loop may repeat without bound for as long as the statutory clock allows, with hold time accumulating on every pass.

The decision itself is applied by a `Manager` and begins with the tally. Let A be the number of `APPROVE` ballots, D the number of `DENY` ballots, and X the number of `ABSTAIN` ballots. Quorum requires the total ballots cast — A plus D plus X — to be at least the association's `quorum_min`; otherwise the decision is rejected with `ERR_QUORUM_NOT_MET`. With quorum met, the outcome depends on the association's tally variant. When `supermajority_required` is true, approval requires at least one non-abstention ballot and three times A to be at least twice the sum of A plus D — abstentions are excluded from the ratio, and the exact two-thirds boundary approves, so two approvals against one denial succeed. When `supermajority_required` is false, approval requires A to strictly exceed D, and a tie denies. The variants genuinely diverge: three approvals against two denials approve under the plurality variant but deny under the supermajority variant, because three-fifths falls short of two-thirds.

An approving decision must also clear the requested window against the construction calendar before it lands: first overlap against the other `ACTIVE` permits of the same property, half-open semantics, surfacing as `ERR_WINDOW_OVERLAP`, then the blackout calendar, closed-interval semantics, surfacing as `ERR_BLACKOUT_CONFLICT`. When several checks would fail at once — say a window conflict and a quorum shortfall — the precedence of §2.9 decides which error is returned, and temporal checks outrank constraint checks. A decision that passes everything moves the application from `UNDER_REVIEW` to `APPROVED_WITH_CONDITIONS`: `decision_outcome` becomes `APPROVED`, the `conditions` list is taken from the decision payload, `decided_at` is stamped, and `version` increments. The approval then cascades: a construction permit is created in `ACTIVE` status with its `window_start` and `window_end` copied from the application's requested window, and the property's `open_permit_count` is recomputed to reflect the new permit.

A denying decision moves the application from `UNDER_REVIEW` to `DENIED`: `decision_outcome` becomes `DENIED`, `decision_reason` is populated from the payload's `denial_reason`, `decided_at` is stamped, and `version` increments. Denial is not the end of the road — §3.6 picks up from here — but `APPROVED_WITH_CONDITIONS`, `DEEMED_APPROVED`, and `APPEAL_DENIED` are terminal: no further transitions are defined from them, and any attempt is rejected with `ERR_INVALID_STATE`.

Even after approval, the conditions remain amendable. A `CommitteeMember` may replace the `conditions` list while the application is `APPROVED_WITH_CONDITIONS` — in any other state the amendment is rejected with `ERR_INVALID_STATE` — and the request must carry `expected_application_version` under the optimistic-concurrency rule of §2.10, with a stale version surfacing as `ERR_STALE_VERSION`. A successful amendment replaces `conditions` with the payload and increments `version` by one.

### 3.5. The Statutory Clock and Deemed Approval

Running underneath the entire committee phase is the statutory review clock, and it is unforgiving. For an application in `SUBMITTED` or `UNDER_REVIEW`, the elapsed review time is the number of countable days strictly after the `submitted_at` date up to and including the current logical date — every day under `CALENDAR` counting, weekdays only under `BUSINESS` counting — minus the application's accumulated `applicant_hold_days`. Time spent in `REVISION_REQUESTED` is therefore excluded from the clock: the hold accumulator freezes it, which is precisely why the revision loop of §3.4 can cycle without consuming the committee's statutory budget.

When the elapsed count reaches the association's `statutory_response_days` — the boundary is inclusive, so the clock fires at exactly that many days — the daily ops checkpoint deems the application approved. Both `SUBMITTED` and `UNDER_REVIEW` applications are subject to this; an application sitting in `REVISION_REQUESTED` is not examined, because its clock is frozen. Deemed approval moves the application to `DEEMED_APPROVED`, sets `decision_outcome` to `APPROVED`, stamps `decided_at`, and increments `version` by one. The same permit cascade as a committee approval follows: an `ACTIVE` construction permit is created with the requested window and the property's `open_permit_count` is recomputed. One crucial difference stands: statutory approval performs no window validation at all — no overlap check, no blackout check — because the permit issues by operation of law rather than by committee discretion. A deemed approval is terminal.

### 3.6. Denial and the Board Appeal

A denied applicant may carry the decision to the board. While the application is `DENIED`, the applicant — `owner_id` equal to `X-User-ID` — files an appeal supplying the `grounds` text. The filing must come within the appeal window: the whole days after the denial's `decided_at` up to and including the filing day must not exceed the association's `appeal_window_days`, and a later filing is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. A successful filing creates an appeal in `PENDING` status with `filed_at` stamped, moves the application from `DENIED` to `UNDER_APPEAL`, and increments the application's `version` by one. An application's appeals are listable by any role.

A `BoardMember` then decides the appeal by supplying an `outcome` of `UPHELD` or `OVERRULED` and an optional `board_note`. Segregation of duties guards this decision from both sides: the decider must not be the applicant, and must not have cast a committee ballot on the appealed application; either breach is rejected with `ERR_SEGREGATION_OF_DUTIES`. The appeal must still be `PENDING` — a second decision attempt is rejected with `ERR_INVALID_STATE`.

Upholding the appeal re-runs the requested window through conflict detection exactly as a committee approval would — overlap against the property's other `ACTIVE` permits, then the blackout calendar — and on success the appeal moves to `UPHELD` while the application moves from `UNDER_APPEAL` to `APPROVED_WITH_CONDITIONS` with `decision_outcome` set to `APPROVED` and `decided_at` restamped. The permit cascade fires identically: an `ACTIVE` permit with the requested window is created and the property's `open_permit_count` is recomputed. Overruling the appeal moves the appeal to `OVERRULED` and drives the application from `UNDER_APPEAL` to `APPEAL_DENIED`, which is terminal. In both branches the appeal records `decided_at`, the `decided_by_owner_id` taken from the decider's `X-User-ID`, and the `board_note`, and the application's `version` increments by one.

### 3.7. Construction Oversight: Permits, Contractors, Extensions, and Inspections

An approved application — whether by committee, by statute, or by the board — yields exactly one construction permit; at most one permit ever exists per application, and the permits of an application are listable as a zero-or-one-entry collection. The permit's `window_start` and `window_end` are copied from the application's requested window at issuance, its `contractor_name` and `contractor_license` begin as empty strings, and its status runs from `ACTIVE` to one of the terminal states `COMPLETED` or `EXPIRED`. A `Manager` sets or replaces the contractor details by supplying `contractor_name` and `contractor_license`; the request must carry `expected_permit_version` under §2.10, with a mismatch rejected as `ERR_STALE_VERSION`, and a successful change increments the permit's `version` by one.

Construction rarely tracks the original plan, so an `ACTIVE` permit's window may be extended by a `Manager` or by a `Homeowner` whose ownership resolves through the permit's application and property under §2.9's context-authorization rule. The extension supplies a `new_window_end` that must be later than the current `window_end`; the whole span from `window_start` to the new end, measured in whole days of the half-open interval, must not exceed `max_window_days` on pain of `ERR_WINDOW_TOO_LONG`; and the extended window must clear conflict detection — overlap against the property's other `ACTIVE` permits first (`ERR_WINDOW_OVERLAP`), then the blackout calendar (`ERR_BLACKOUT_CONFLICT`). A successful extension writes the new `window_end`, keeps the permit `ACTIVE`, and increments `version` by one.

When the work is done, the applicant requests a completion inspection. The permit must be `ACTIVE` — otherwise `ERR_INVALID_STATE` — and the caller must own the parent application, with its `owner_id` equal to `X-User-ID`, otherwise `ERR_UNAUTHORIZED`. The request creates an inspection in `SCHEDULED` status, bound to the inspected permit through its `permit_id`, whose `attempt_no` is one plus the number of inspections the permit already has — so a permit's first inspection is attempt 1 — with `scheduled_at` stamped. The inspections of a permit are listable by any role.

An `Inspector` records the outcome of a `SCHEDULED` inspection by supplying a `result` of `PASS` or `FAIL` with optional `result_notes`; the server stamps `recorded_at`. On a `PASS`, the inspection moves to `PASSED` — its terminal state — and the permit moves to `COMPLETED` with `completed_at` stamped, bubbling a recompute of the property's `open_permit_count`. Late completion is honored: if the permit had already fallen to `EXPIRED`, a passing inspection still completes it, and in that case every violation sourced from that permit — matched by `source_permit_id` — that still stands `OPEN` or `ESCALATED` is moved to `REMEDIATED`, those violations' fines move from `ACCRUING` to `STOPPED`, and the property's `outstanding_fine_balance_cents` and `compliance_posture` are recomputed.

On a `FAIL`, the inspection moves to `FAILED_REMEDIATION` and a three-link cascade fires: a violation is created in `OPEN` status with `kind` `CONDITION_BREACH`, carrying both `source_inspection_id` and `source_permit_id`; the violation's creation creates its fine in `ACCRUING` status per §3.8; and the fine's creation recomputes the property's balance and posture. The violations created by a failed inspection are listable as a zero-or-one-entry collection.

A failed inspection is not the end of the permit. Once the violation it created — the violation whose `source_inspection_id` points back to this inspection — stands `REMEDIATED`, a `Manager` may reschedule: the inspection moves from `FAILED_REMEDIATION` back to `SCHEDULED`, `attempt_no` increments by one, `scheduled_at` is restamped, `recorded_at` is cleared, and `version` increments by one. Rescheduling while that violation remains unremediated fails the cross-entity state gate with `ERR_INVALID_STATE`. The re-inspection loop is cyclic and may repeat as often as needed.

Permits that outlive their windows are caught by the daily checkpoint: when the current logical date is later than an `ACTIVE` permit's `window_end` and no `PASSED` inspection exists for that permit, the permit moves to `EXPIRED`, and the same three-link cascade fires — an `OPEN` violation of `kind` `INCOMPLETE_CONSTRUCTION` carrying the `source_permit_id`, its `ACCRUING` fine, and the property recompute.

### 3.8. Enforcement: Violations, Fines, Remediation, and Liens

Violations enter the system in three ways: manager report, failed inspection, or permit expiry. A `Manager` reports a violation on a property — the violation is bound to its subject property through `property_id` — by supplying a `kind` of `UNAPPROVED_WORK`, `CONDITION_BREACH`, or `INCOMPLETE_CONSTRUCTION`, a `description` of the infraction, and an optional `application_id` of the related application — the empty string when there is none, as with unapproved work. Manager-reported violations leave `source_inspection_id` and `source_permit_id` empty. However a violation arises, it starts `OPEN`, and its creation always fires the same cascade: exactly one fine is created for the violation — they are linked one-to-one by the fine's `violation_id`, and the fines of a violation are listable as an exactly-one-entry collection — in `ACCRUING` status, and the property's balance and posture are recomputed.

The fine snapshots the association's configuration at creation, so later reconfiguration never rewrites history: `mode_snapshot` copies `fine_mode`, `base_cents` copies `base_fine_cents` and seeds the accrued total, `daily_rate_cents` copies `daily_fine_cents`, and `grace_days_snapshot` and `escalation_multiplier_bp_snapshot` copy their association counterparts. The fine's `started_at` marks accrual day zero, `accrued_through_date` starts equal to the creation date, and `settled_cents` and `waived_cents` start at zero. The violation itself is stamped with a `remediation_deadline` set to the creation date plus the association's `remediation_days`.

Accrual runs day by day. The day index counts whole days after the `started_at` date, so day 1 is the day after creation. Under the `SIMPLE_DAILY` snapshot, every day adds `daily_rate_cents`. Under the `TIERED_ESCALATION` snapshot, a day whose index is at most `grace_days_snapshot` still adds the base `daily_rate_cents` — the grace day itself included — while a day whose index exceeds the grace count adds the escalated increment: `daily_rate_cents` multiplied by `escalation_multiplier_bp_snapshot` and divided by 10000, rounded half up to a whole cent for that day. The daily checkpoint advances every `ACCRUING` fine from the day after its `accrued_through_date` through the current logical date, rounding each day's increment before adding it into `accrued_cents` — never summing raw amounts and rounding once, per §2.7 — and restamps `accrued_through_date` to the current date. Only `ACCRUING` fines accrue; `STOPPED` and `SETTLED` fines never move. The two modes genuinely diverge: a fine created with a base of 10000 cents, a daily rate of 1000 cents, a grace of 3 days, and a 20000-basis-point multiplier stands at 17000 cents after five accrual days under tiered escalation — the base plus three days of 1000 plus two days of 2000 — against 15000 cents under simple daily. Accrual is also brought up to date when a fine stops or settles, so balances are current at those moments.

Violations that outlive their deadline escalate: the daily checkpoint moves an `OPEN` violation whose `remediation_deadline` has passed — the current date is later than the deadline — to `ESCALATED`, stamping `escalated_at`. Escalation changes nothing about accrual; the fine keeps accruing either way.

Remediation belongs to the property's primary owner: a `Homeowner` whose `X-User-ID` equals the property's `primary_owner_id` marks an `OPEN` or `ESCALATED` violation remediated, optionally supplying a `remediation_note`. The violation moves to `REMEDIATED` with `remediated_at` stamped — a terminal state — and its fine, if still `ACCRUING`, halts at the remediation date, moving to `STOPPED` with `stopped_at` stamped; the property's balance and posture are then recomputed. Violations are listable by property with an optional `status` filter, by application, and by permit.

Money leaves a fine through two doors. Settlement is all-or-nothing: a `Homeowner` settles a fine that is `ACCRUING` or `STOPPED` by paying `amount_cents` equal to the fine's `outstanding_cents` exactly — any other amount is rejected with `ERR_SETTLEMENT_AMOUNT_MISMATCH` — moving the fine to `SETTLED`, setting `settled_cents` to the paid `amount_cents`, zeroing `outstanding_cents`, stamping `settled_at`, and recomputing the property. Waiver is the manager's compensating action and may be partial: a `Manager` waives by supplying `amount_cents` and a `reason`, with the amount not exceeding the fine's `outstanding_cents` — a larger waiver is rejected with `ERR_WAIVER_EXCEEDS_OUTSTANDING`. Waiving is permitted on `ACCRUING` and `STOPPED` fines alike, adds the amount to `waived_cents`, recomputes `outstanding_cents` and the property, and increments the fine's `version` by one. Both doors conserve the fine identity of §2.5: `accrued_cents` always equals `settled_cents` plus `waived_cents` plus `outstanding_cents`.

At the top of the enforcement ladder sits the lien. The daily checkpoint auto-files a lien on a property when three conditions hold together: the property's `outstanding_fine_balance_cents` is at or above the association's `lien_threshold_cents`, the oldest unpaid fine is at least `lien_min_age_days` old, and no `FILED` lien already exists for the property. The lien captures the property's balance at that instant in `amount_at_filing_cents`, stamps `filed_at`, and starts in `FILED` status — which flips the property's `compliance_posture` to `LIENED` and, per §3.3, blocks new application submissions with `ERR_PROPERTY_LIENED`. A `Manager` satisfies a filed lien only once the property's outstanding balance has returned to zero; satisfying earlier is rejected with `ERR_LIEN_BALANCE_OUTSTANDING`. Satisfaction moves the lien to `SATISFIED` with `satisfied_at` stamped, and the posture recomputes: with the balance at zero and no `FILED` lien remaining, the property returns from `LIENED` to `CLEAR`. A property's liens are listable by any role.

The property's posture machine, for completeness, moves `CLEAR` to `FINES_OUTSTANDING` when the balance becomes positive with no `FILED` lien, `FINES_OUTSTANDING` to `LIENED` when a lien files, `FINES_OUTSTANDING` back to `CLEAR` when the balance returns to zero with no `FILED` lien, and `LIENED` to `CLEAR` after satisfaction at a zero balance.

Finally, the daily ops checkpoint itself. A `Manager` invokes it at the current logical date, and it applies five steps in fixed order: first, deemed approvals for `SUBMITTED` and `UNDER_REVIEW` applications that have hit the statutory deadline; second, accrual for every `ACCRUING` fine using the per-day rounded increments above; third, escalation of `OPEN` violations past their `remediation_deadline`; fourth, lien auto-filing on the balance and age conditions above; and fifth, expiry of `ACTIVE` permits past their `window_end`. The checkpoint is idempotent per date — `accrued_through_date` tracking ensures a second run for the same date accrues nothing further — and its response reports `applications_deemed_approved`, `fines_accrued`, `violations_escalated`, `liens_filed`, and `permits_expired`. The companion clock capability sets the logical clock from a supplied `to_iso8601` and returns `current_utc`.

## 4. Endpoint Definitions

Operations that create a new resource — an association, an owner, a property, a blackout period, a variance, an application, an attachment, an appeal, an inspection, or a violation — return `201 Created`. Operations that modify an existing resource return `200 OK`; this includes all state-transition actions, settlements, and waivers. Casting or recasting a committee ballot returns `201 Created` whether the vote row is new or recast. The two test-driving operations — setting the logical clock and running the daily checkpoint — return `200 OK` with summary payloads. The complete request and response shapes of every operation are as narrated in §3; the table below is a navigational summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/arc/associations` | Create an association with its review, fine, and lien configuration | Manager |
| GET | `/arc/associations/{id}` | Read an association | Any |
| POST | `/arc/associations/{id}/owners` | Register an owner/member | Manager |
| GET | `/arc/associations/{id}/owners` | List owners of an association (paginated) | Any |
| GET | `/arc/owners/{id}` | Read an owner | Any |
| POST | `/arc/associations/{id}/properties` | Register a property/lot | Manager |
| GET | `/arc/associations/{id}/properties` | List properties of an association (paginated) | Any |
| GET | `/arc/properties/{id}` | Read a property including computed balance, posture, and open permit count | Any |
| GET | `/arc/owners/{id}/properties` | List properties whose primary owner is this owner | Any |
| POST | `/arc/associations/{id}/blackouts` | Declare a closed-interval construction blackout period | Manager |
| GET | `/arc/associations/{id}/blackouts` | List blackout periods | Any |
| POST | `/arc/associations/{id}/variances` | Record an approved variance precedent | Manager |
| GET | `/arc/associations/{id}/variances` | Search variance precedents, optionally filtered by guideline section | Any |
| POST | `/arc/properties/{id}/applications` | Create a DRAFT architectural review application | Homeowner |
| GET | `/arc/applications/{id}` | Read an application | Any |
| GET | `/arc/properties/{id}/applications` | List applications of a property | Any |
| GET | `/arc/owners/{id}/applications` | List applications filed by an owner | Any |
| POST | `/arc/applications/{id}/attachments` | Attach a drawing or material sample to a DRAFT or REVISION_REQUESTED application | Homeowner |
| GET | `/arc/applications/{id}/attachments` | List attachments of an application | Any |
| POST | `/arc/applications/{id}/submit` | Submit a DRAFT application (posture gate plus completeness) | Homeowner |
| POST | `/arc/applications/{id}/start-review` | Open committee review | Manager |
| POST | `/arc/applications/{id}/request-revision` | Request applicant revisions (opens the applicant hold) | CommitteeMember |
| POST | `/arc/applications/{id}/resubmit` | Resubmit after revisions (closes the hold, returns to review) | Homeowner |
| POST | `/arc/applications/{id}/votes` | Cast or recast a committee ballot | CommitteeMember |
| GET | `/arc/applications/{id}/votes` | List ballots of an application | Any |
| GET | `/arc/owners/{id}/votes` | List ballots cast by an owner | Any |
| POST | `/arc/applications/{id}/decide` | Tally ballots and apply the committee decision | Manager |
| POST | `/arc/applications/{id}/conditions` | Amend approval conditions (OCC-guarded) | CommitteeMember |
| POST | `/arc/applications/{id}/appeals` | Appeal a DENIED application to the board | Homeowner |
| GET | `/arc/applications/{id}/appeals` | List appeals of an application | Any |
| POST | `/arc/appeals/{id}/decide` | Decide an appeal (segregation of duties enforced) | BoardMember |
| GET | `/arc/permits/{id}` | Read a construction permit | Any |
| GET | `/arc/applications/{id}/permits` | List permits of an application (zero or one entries) | Any |
| POST | `/arc/permits/{id}/contractor-change` | Set or replace contractor details on an ACTIVE permit (OCC-guarded) | Manager |
| POST | `/arc/permits/{id}/extensions` | Extend the construction window of an ACTIVE permit | Manager, Homeowner |
| POST | `/arc/permits/{id}/request-inspection` | Schedule a completion inspection | Homeowner |
| GET | `/arc/permits/{id}/inspections` | List inspections of a permit | Any |
| GET | `/arc/inspections/{id}` | Read an inspection | Any |
| POST | `/arc/inspections/{id}/record` | Record a PASS or FAIL result on a SCHEDULED inspection | Inspector |
| POST | `/arc/inspections/{id}/reschedule` | Reschedule a FAILED_REMEDIATION inspection after its violation is remediated | Manager |
| POST | `/arc/properties/{id}/violations` | Report a violation (e.g., unapproved work) | Manager |
| GET | `/arc/violations/{id}` | Read a violation | Any |
| GET | `/arc/properties/{id}/violations` | List violations of a property | Any |
| GET | `/arc/applications/{id}/violations` | List violations linked to an application | Any |
| GET | `/arc/applications/{id}/variances` | List variance precedents referencing an application | Any |
| GET | `/arc/permits/{id}/violations` | List violations linked to a permit | Any |
| GET | `/arc/inspections/{id}/violations` | List violations created by a failed inspection (zero or one entries) | Any |
| POST | `/arc/violations/{id}/remediate` | Mark a violation remediated; stops fine accrual | Homeowner |
| GET | `/arc/violations/{id}/fines` | List fines of a violation (exactly one entry) | Any |
| POST | `/arc/fines/{id}/settle` | Settle a fine in full (amount must equal the outstanding balance exactly) | Homeowner |
| POST | `/arc/fines/{id}/waive` | Waive part of a fine (compensating action) | Manager |
| GET | `/arc/properties/{id}/liens` | List liens of a property | Any |
| POST | `/arc/liens/{id}/satisfy` | Satisfy a filed lien once the property balance is zero | Manager |
| POST | `/arc/_clock/set_current_utc` | Set the logical clock | Manager |
| POST | `/arc/_sweeps/daily` | Run the daily ops checkpoint at the current logical date | Manager |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; the table below is the identifier and status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ASSOCIATION_NOT_FOUND` | 404 Not Found |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_FINE_NOT_FOUND` | 404 Not Found |
| `ERR_LIEN_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_VARIANCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROPERTY_LIENED` | 409 Conflict |
| `ERR_INCOMPLETE_SUBMISSION` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BLACKOUT_CONFLICT` | 422 Unprocessable Entity |
| `ERR_WINDOW_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_PRECEDENT_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WAIVER_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_LIEN_BALANCE_OUTSTANDING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
