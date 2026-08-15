# External Audit Coordination & PBC Management API — Product Requirements Document

## 1. Introduction

Every year, the corporate controller's office runs the same gauntlet: an external audit firm arrives with a prepared-by-client (PBC) request list, and for weeks the two parties trade evidence files, queries, sampling logistics, proposed adjustments, and fee negotiations — all against an immovable filing deadline. Today this coordination lives in email threads and spreadsheets, where evidence versions are lost, query turnaround is unmeasured, and no one can say with confidence whether the passed-adjustment schedule has crept past materiality. This document specifies an API that makes the engagement itself the system of record.

The External Audit Coordination & PBC Management API governs the full lifecycle of a single audit engagement, from planning through fieldwork to report issuance. It tracks PBC requests and their versioned evidence uploads, the auditor query log with measured response turnaround, sampling requests coordinated across client locations, fieldwork visit scheduling, the audit adjustment and passed-adjustment schedule, the management representation letter, and fee/scope change negotiation between the controller's office and the audit firm. Three roles share the workload — the `Controller`, the `Preparer`, and the `ExternalAuditor` — with segregation-of-duties and counter-party-approval rules enforced where financial exposure demands them. All resources are mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly three roles, spelled precisely as follows: `Controller`, `Preparer`, and `ExternalAuditor`. Each endpoint admits a defined set of roles (§4); a request whose role is not admitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

For all three roles, `X-User-ID` is an **opaque** operator identifier not tied to any persisted entity. Concretely: when `X-User-Role` is `Controller`, `X-User-ID` is an opaque identifier the server may record — for example as `disposition_by_user_id` on a dispositioned adjustment or `signed_by_user_id` on a signed representation letter — but never compares against any entity's `id`. When `X-User-Role` is `Preparer`, `X-User-ID` is likewise opaque; the server records it as `uploader_user_id` on evidence uploads and `prepared_by_user_id` on representation letters, and compares it — as a plain string — to a PBC request's `owner_user_id` where ownership rules apply, without ever treating it as an entity `id`. When `X-User-Role` is `ExternalAuditor`, `X-User-ID` is again opaque; the server records it as `auditor_user_id` on queries and fieldwork visits and as `proposed_by_user_id` on adjustments, with no comparison to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — engagements, locations, PBC requests, evidence uploads, queries, sampling requests, fieldwork visits, adjustments, representation letters, and fee change requests — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any modification to the resource.
- `version` (integer): a system-managed integer that increments by one with every modification, including modifications caused by cascades and by derived-field recomputation.

No entity in this domain is exempt from this convention; all ten resource types carry all four fields. Because cascades from an engagement-level event (cancellation, representation-letter signing) touch many children at once, observers should treat a child's `version` and `updated_at` as moving whenever the cascade reaches it.

### 2.5. Nested Resource Retrieval

Requests that address a resource through a path containing one or more identifiers are validated strictly left-to-right. The server confirms the existence of each identifier in path order and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve: `ERR_ENGAGEMENT_NOT_FOUND` for engagements, `ERR_LOCATION_NOT_FOUND` for locations, `ERR_PBC_NOT_FOUND` for PBC requests, `ERR_EVIDENCE_NOT_FOUND` for evidence uploads, `ERR_QUERY_NOT_FOUND` for queries, `ERR_SAMPLING_NOT_FOUND` for sampling requests, `ERR_VISIT_NOT_FOUND` for fieldwork visits, `ERR_ADJUSTMENT_NOT_FOUND` for adjustments, `ERR_REP_LETTER_NOT_FOUND` for representation letters, and `ERR_FEE_CHANGE_NOT_FOUND` for fee change requests. Existence validation precedes all state and business checks, so a request aimed at a non-existent parent never surfaces a child-level or business-level error.

### 2.6. Engagement Posture and Cross-Aggregate Consistency

Beyond its lifecycle `status`, every engagement carries a derived **`posture`** with three values. The posture is `LOCKED` whenever the engagement's representation letter has reached `SIGNED`; otherwise it is `CLOSING` when the engagement's `status` is `FIELDWORK_COMPLETE`; otherwise it is `OPEN`. Posture is recomputed automatically whenever the underlying facts change — completing fieldwork moves an engagement into `CLOSING`, and signing the representation letter moves it into `LOCKED`.

A `LOCKED` posture freezes the engagement's working surface. While an engagement is `LOCKED`, every state-mutating operation other than report issuance and reads is rejected with `ERR_ENGAGEMENT_POSTURE_LOCKED`: creating PBC requests, uploading evidence, submitting a PBC request for review, recording an auditor review decision, raising queries, creating sampling requests, scheduling fieldwork visits, proposing adjustments, dispositioning adjustments, proposing fee change requests, creating a representation letter draft, and submitting a representation letter for signature are all forbidden. Issuing the audit report remains permitted — it is the very act a `LOCKED` engagement is waiting for.

Hierarchy cuts the other way as well: child activity mutates the parent. Uploading evidence and signing the representation letter each increment the parent engagement's `version` by one; counters such as `open_pbc_count` and `open_query_count` move as requests and queries open and close; and each such mutation refreshes the engagement's `updated_at`. The server performs these reconciliations automatically, without requiring a client request addressed at the engagement itself.

### 2.7. Monetary Values: Integer Cents, Fee Arithmetic, and Rounding

All monetary quantities are integers denominated in cents — `base_fee_cents`, `materiality_cents`, `total_fee_cents`, `amount_cents`, `delta_cents`, and `passed_adjustment_total_cents` — and monetary arithmetic never involves rounding. An engagement's `total_fee_cents` is defined as its `base_fee_cents` plus the sum of `delta_cents` over the engagement's fee change requests whose status is `APPROVED`; proposals still in `PROPOSED`, and requests in `REJECTED` or `WITHDRAWN`, contribute nothing. One read-time nuance applies: while any fee change request remains `PROPOSED`, the `total_fee_cents` reported when reading an engagement is a **provisional** figure equal to the base fee plus the sum of deltas in either `PROPOSED` or `APPROVED` status — a forward-looking estimate of where the fee will land. Once no `PROPOSED` requests remain, the reported figure is the **final** one, equal to the base fee plus approved deltas only.

The one non-monetary computed figure in the system, the PBC aging score described in §3.2, is rounded to exactly 2 decimal places using round-half-up.

### 2.8. The Logical Clock

The server maintains a logical clock that governs every timestamp it writes — `uploaded_at` on evidence, `raised_at` and `responded_at` on queries, `signed_at` on representation letters — and every duration it derives, such as query turnaround and the PBC aging score. At boot, the logical clock is pinned to `2026-08-01T00:00:00Z`. A `Controller` may advance it to an arbitrary ISO 8601 UTC instant by supplying `to_iso8601` to the clock-setting capability; the response echoes the new logical time as `now_iso8601`. Because fixture dates sit at or after the boot instant, any test of deadlines, aging, or turnaround must drive time forward through this capability rather than relying on wall-clock passage.

### 2.9. Optimistic Concurrency Control on the Engagement

Two write operations are guarded by optimistic concurrency control against the parent engagement's `version`, because each is exactly the kind of write that must not proceed against a stale view of the engagement.

Uploading evidence requires the request body to carry `expected_engagement_version`, a non-optional field holding the engagement `version` the client last observed. If the engagement's current `version` does not match — because signing or cancellation activity has advanced it since the client's last read — the upload is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), preventing evidence from being attached to an engagement state the client has not observed.

Signing a representation letter carries the identical guard: the request must carry `expected_engagement_version` matching the engagement's current `version`, and a mismatch is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). The sign transition recomputes posture to `LOCKED` and cascades freezes across open PBC requests, so the signer must have observed the latest engagement state. No endpoint other than these two accepts a version field.

### 2.10. Validation Order of Precedence

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. First, header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role authorization for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`). Third, left-to-right existence of path identifiers (the 404 family of §2.5). Fourth, the engagement posture lock (`ERR_ENGAGEMENT_POSTURE_LOCKED`). Fifth, target-state preconditions for the requested transition — the `ERR_..._NOT_...` 409 family, such as `ERR_PBC_NOT_UNDER_REVIEW` or `ERR_FEE_CHANGE_NOT_PROPOSED`. Sixth, the representation-letter segregation-of-duties rule (`ERR_REP_LETTER_SOD_VIOLATION`). Seventh, the fee-change counter-party rule (`ERR_FEE_CHANGE_SELF_APPROVAL`). Eighth, request-owner identity (`ERR_NOT_REQUEST_OWNER`). Ninth, request field shape — the 400 family covering evidence file size, hash format, sampling windows, sample size, adjustment amount, fee delta, sampling location lists, and visit windows. Tenth, sampling-window overlap (`ERR_SAMPLING_WINDOW_OVERLAP`). Eleventh, fieldwork-visit overlap (`ERR_VISIT_WINDOW_OVERLAP`). Twelfth, the passed-adjustment materiality gate (`ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY`). Thirteenth, the fee-floor check (`ERR_FEE_WOULD_GO_NONPOSITIVE`). Fourteenth, filing-deadline alignment (`ERR_DEADLINE_AFTER_FILING`). Fifteenth and last, stale-version rejection (`ERR_STALE_ENGAGEMENT_VERSION`). A request is rejected at the first check that fails; later checks are not evaluated.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Engagement: Registration, Locations, and Commencement

A `Controller` opens an engagement by supplying the audited entity's legal `client_name`, its `fiscal_year_end` date, the negotiated `base_fee_cents` (which must be greater than zero), the overall engagement `materiality_cents` (likewise greater than zero), and the `filing_deadline` date that will discipline the whole timeline. A new engagement starts in `PLANNING` status with `posture` derived as `OPEN`, `total_fee_cents` equal to `base_fee_cents`, and all three derived counters — `open_pbc_count`, `open_query_count`, and `passed_adjustment_total_cents` — at zero.

Before fieldwork can begin, the engagement needs geography. A `Controller` registers each audit location with an `engagement_id`, a short `location_code` unique within the engagement, a human-readable `name`, and a location-level `materiality_cents` that must be greater than zero and no greater than the engagement's own `materiality_cents`; a location whose materiality exceeds the engagement's is rejected with `ERR_LOCATION_MATERIALITY_TOO_HIGH`.

Commencing fieldwork is the `Controller`'s act that moves the engagement from `PLANNING` to `FIELDWORK`. It is rejected with `ERR_ENGAGEMENT_NOT_IN_PLANNING` unless the engagement is in `PLANNING`, and with `ERR_NO_LOCATIONS_DEFINED` if not a single location has been registered. Only in `FIELDWORK` does the evidence pipeline open.

An engagement can also be abandoned. Cancellation by a `Controller` is permitted from `PLANNING` or `FIELDWORK`; from any later state it is rejected with `ERR_ENGAGEMENT_NOT_CANCELLABLE`. Cancellation lands on `CANCELLED` and cascades through every child aggregate: every PBC request not yet in a terminal state (`OPEN`, `IN_PROGRESS`, `SUBMITTED`, or `REJECTED`) becomes `FROZEN`; every evidence upload still `PENDING_REVIEW` becomes `INVALIDATED`; every sampling request in `DRAFT`, `DISPATCHED`, or `IN_PROGRESS` becomes `CANCELLED`; every `SCHEDULED` fieldwork visit becomes `CANCELLED`; every `PROPOSED` adjustment becomes `REJECTED` with its `disposition_rationale` set to `ENGAGEMENT_CANCELLED`; and every `PROPOSED` fee change request becomes `WITHDRAWN`.

### 3.2. The PBC Cycle: Ownership, Evidence Versions, and Auditor Review

The prepared-by-client list is the engagement's backbone. An `ExternalAuditor` adds a request with an `engagement_id`, a short `title` describing the evidence sought, the `owner_user_id` of the controller-office user (a `Preparer`, or the `Controller`) accountable for delivery, and a `due_date`. The due date must fall on or before the engagement's `filing_deadline`; a later date is rejected with `ERR_DEADLINE_AFTER_FILING`. A new request starts `OPEN` with `rejection_count` at zero, and the engagement's `open_pbc_count` increments by one. The request list can be filtered by `engagement_id` and `status`, and each open item in the list response carries a computed `pbc_aging_score` (below). The request's `current_evidence_id` remains null until an evidence upload is first accepted.

Fulfilling a request is owner-gated work. Uploading a new evidence version is a `Preparer` action permitted only while the request is `OPEN` or `REJECTED` — otherwise `ERR_PBC_NOT_OPEN_FOR_UPLOAD` — and only while the engagement is in `FIELDWORK` (`ERR_ENGAGEMENT_NOT_IN_FIELDWORK`) with posture `OPEN`. The uploader must be the request's owner: `X-User-ID` is compared to `owner_user_id`, and a mismatch is rejected with `ERR_NOT_REQUEST_OWNER`. The payload carries the original `file_name`, the `file_size_bytes` (which must be greater than zero and no greater than `MAX_EVIDENCE_BYTES`, else `ERR_INVALID_EVIDENCE_FILE`), and a `sha256` content hash of exactly 64 lowercase hexadecimal characters (else `ERR_INVALID_HASH`). As covered in §2.9, the payload must also carry `expected_engagement_version`. A successful upload creates an `EvidenceUpload` in `PENDING_REVIEW`, stamped with the logical clock as `uploaded_at`, recorded with the uploader's `X-User-ID` as `uploader_user_id`, and assigned a `version_seq` equal to one more than the highest existing `version_seq` on that request (the first upload therefore takes sequence 1). The request moves to `IN_PROGRESS`, its `rejection_count` is left unchanged, and — per §2.6 — the parent engagement's `version` increments. Evidence uploads can be listed with filters on `pbc_request_id`, `engagement_id`, and `status`.

Once at least one upload stands `PENDING_REVIEW`, the owner submits the request for review; submitting from any state other than `IN_PROGRESS` is rejected with `ERR_PBC_NOT_SUBMITTABLE`, submitting without pending evidence with `ERR_NO_PENDING_EVIDENCE`, and submitting as anyone but the owner with `ERR_NOT_REQUEST_OWNER`. The request is now `SUBMITTED` and belongs to the auditor.

Review is the `ExternalAuditor`'s decision, expressed through a payload `decision` of `ACCEPT` or `REJECT` with an optional `rationale`; reviewing a request not in `SUBMITTED` is rejected with `ERR_PBC_NOT_UNDER_REVIEW`. On `ACCEPT`, every `PENDING_REVIEW` upload becomes `ACCEPTED`, any earlier `ACCEPTED` uploads for the same request become `SUPERSEDED` so only the latest survives, `current_evidence_id` is set to the latest accepted upload's `id`, `rejection_count` resets to zero, and the engagement's `open_pbc_count` decrements by one. On `REJECT`, every `PENDING_REVIEW` upload becomes `REJECTED` and the request's `rejection_count` increments by one, returning the request to `REJECTED` — from which the owner may upload again and repeat the cycle. `ACCEPTED` is terminal for the request; the only way out of the working states otherwise is the system-driven freeze to `FROZEN`, which cascades from engagement cancellation or representation-letter signing and reaches `OPEN`, `IN_PROGRESS`, `SUBMITTED`, and `REJECTED` requests alike.

The `pbc_aging_score` reported on list responses is computed for each request in `OPEN`, `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` status, against the current logical clock, in a pinned evaluation order. First, `recency_days` is the number of days between the most recent upload's `uploaded_at` and now, floored at zero; if the request has no evidence yet, the days between the request's `created_at` and now are used instead. Second, freshness is one divided by the quantity one plus `recency_days` — a value greater than zero and at most one. Third, a backlog multiplier of one plus one-tenth of the engagement's current `open_query_count` is read from the engagement row as it currently stands, not recomputed inside the formula. Fourth, the score is one hundred times the quantity one minus freshness, multiplied by the backlog multiplier, rounded half-up to 2 decimal places.

### 3.3. Query Log Discipline and Response Turnaround

Auditors raise questions continuously, and the query log measures how quickly the client answers. An `ExternalAuditor` raises a query with an `engagement_id`, a `subject` line, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and optionally a `pbc_request_id` linking the query to the request it challenges (null when the query stands alone). The query opens in `OPEN` status with `raised_at` stamped from the logical clock, the raiser's `X-User-ID` recorded as `auditor_user_id`, `responded_at` null, and the engagement's `open_query_count` incremented by one. The query list supports filtering by `engagement_id` and `status`.

Routing moves a query from `OPEN` to `AWAITING_CLIENT`; routing anything not in `OPEN` is rejected with `ERR_QUERY_NOT_OPEN`. The client's answer is a `Preparer` action carrying `response_text`, permitted only from `AWAITING_CLIENT` (`ERR_QUERY_NOT_AWAITING_CLIENT`). Ownership follows the link: when the query's `pbc_request_id` is set, the responder's `X-User-ID` must equal that request's `owner_user_id`, else `ERR_NOT_REQUEST_OWNER`. A successful response stamps `responded_at` from the logical clock, moves the query to `RESPONDED`, and computes `turnaround_hours` as the elapsed seconds between `raised_at` and `responded_at` divided by 3600 and rounded up to a whole hour — with the boundary convention that a gap landing exactly on the hour yields that hour count itself, so exactly 7200 seconds yields 2, not 3. Until the first response is logged, `turnaround_hours` is null.

Escalation is the auditor's pressure valve: from either `OPEN` or `AWAITING_CLIENT`, escalating moves the query to `ESCALATED` (the same `ERR_QUERY_NOT_OPEN` guards attempts from any other state). Closure, also the auditor's, is permitted from `RESPONDED` or `ESCALATED` — otherwise `ERR_QUERY_NOT_CLOSABLE` — and lands on the terminal `CLOSED` state, decrementing the engagement's `open_query_count` by one. Nothing reopens a closed query.

### 3.4. Sampling Coordination Across Locations

Sampling ties evidence gathering to geography. An `ExternalAuditor` creates a sampling request with an `engagement_id`, a `title`, a non-empty `location_ids` array whose every element must reference a location registered under the same engagement, a `window_start` date, a `window_end` date, and a `sample_size` giving the number of items to pull per location. Field shape is enforced at creation: `window_end` strictly after `window_start` (`ERR_INVALID_SAMPLING_WINDOW`), `sample_size` at least 1 (`ERR_INVALID_SAMPLE_SIZE`), and the location array non-empty (`ERR_NO_SAMPLING_LOCATIONS`). A new request starts in `DRAFT`; the list filters by `engagement_id` and `status`.

Dispatch is where coordination happens. Dispatching — an `ExternalAuditor` action — requires the request to be in `DRAFT` (`ERR_SAMPLING_NOT_DRAFT`), re-checks that `window_end` is strictly after `window_start` (`ERR_INVALID_SAMPLING_WINDOW`) and that `location_ids` is non-empty (`ERR_NO_SAMPLING_LOCATIONS`), and then runs the overlap check. Windows are **half-open**: the window includes `window_start` and excludes `window_end`. For each location in the request, the server examines the engagement's other sampling requests in `DISPATCHED` or `IN_PROGRESS` status that cover the same location (`DRAFT`, `COMPLETE`, and `CANCELLED` requests are ignored). A conflict exists only when the new window's `window_start` falls before the existing window's `window_end` **and** the existing window's `window_start` falls before the new window's `window_end`; windows that merely touch — the new `window_start` equal to an existing `window_end` — do not overlap. Any conflict rejects the dispatch with `ERR_SAMPLING_WINDOW_OVERLAP`. Dispatch also applies the per-location materiality lens: each location's exposure is measured against that location's own `materiality_cents` (not the engagement-level figure), and dispatch remains allowed while the per-location passed total is less than or equal to the location materiality — a different operator and a different threshold source than the engagement-level report gate of §3.8.

From `DISPATCHED`, a `Preparer` starts the work (`ERR_SAMPLING_NOT_DISPATCHED` guards other states), moving the request to `IN_PROGRESS`; from `IN_PROGRESS`, a `Preparer` marks it `COMPLETE` (`ERR_SAMPLING_NOT_IN_PROGRESS`). An `ExternalAuditor` may cancel from `DRAFT`, `DISPATCHED`, or `IN_PROGRESS` — from anything else, `ERR_SAMPLING_NOT_CANCELLABLE` — landing on the terminal `CANCELLED` state alongside `COMPLETE`.

### 3.5. Fieldwork Visit Scheduling

Visits put auditors on site. An `ExternalAuditor` schedules a visit with an `engagement_id`, the `auditor_user_id` of the firm staff member attending, the `location_id` being visited, and a `visit_start` and `visit_end` date. Visit windows are **closed intervals** — both endpoints are included — and `visit_end` on or after `visit_start` is enforced as `ERR_INVALID_VISIT_WINDOW`. Timeline discipline bites here too: `visit_end` must fall strictly before the engagement's `filing_deadline`, else `ERR_DEADLINE_AFTER_FILING`. A new visit starts `SCHEDULED`, and the list filters by `engagement_id`, `location_id`, and `status`.

Scheduling enforces per-auditor sanity. Against every existing `SCHEDULED` visit for the same `auditor_user_id`, an overlap exists whenever the new `visit_start` is on or before the existing `visit_end` and the existing `visit_start` is on or before the new `visit_end` — so two visits sharing even a single calendar date conflict. A buffer rule applies on top: when the new visit begins after an existing visit ends, at least one full day must separate them, meaning the new `visit_start` must be at least one day after every existing `visit_end` for that auditor. Either failure rejects the scheduling with `ERR_VISIT_WINDOW_OVERLAP`. Visits for different auditors never interfere.

Completion and cancellation are both `ExternalAuditor` actions from `SCHEDULED`, guarded by `ERR_VISIT_NOT_SCHEDULED`, landing respectively on the terminal states `COMPLETED` and `CANCELLED`.

### 3.6. Proposed Adjustments and the Passed-Adjustment Schedule

When the auditor finds a misstatement, the adjustment workflow begins. An `ExternalAuditor` proposes an adjustment with an `engagement_id`, a `description` of its nature, an `amount_cents` holding the absolute value in cents (which must be greater than zero, else `ERR_INVALID_ADJUSTMENT_AMOUNT`), and a `direction` of `DEBIT` or `CREDIT` naming its effect on income. The proposal lands in `PROPOSED` disposition with the proposer's `X-User-ID` recorded as `proposed_by_user_id`. The adjustment list — which doubles as the passed-adjustment schedule — filters by `engagement_id` and by `disposition`.

Disposition belongs to the `Controller`, whose payload carries a `disposition` of `ACCEPT`, `REJECT`, or `PASS` and a `rationale`. The adjustment must be in `PROPOSED` (`ERR_ADJUSTMENT_NOT_PROPOSED`) and the engagement posture must not be `LOCKED` (`ERR_ENGAGEMENT_POSTURE_LOCKED`, per §2.6). The three branches differ in their rationale discipline. `ACCEPT` treats `rationale` as optional — the recorded `disposition_rationale` is the payload value when provided and null otherwise. `REJECT` and `PASS` both require a `rationale`; omitting it is rejected with `ERR_RATIONALE_REQUIRED`. All three branches record the acting `Controller`'s `X-User-ID` as `disposition_by_user_id`. `PASS` carries one further consequence: it records that the client refused to book the item, moving it to the passed-adjustment schedule and incrementing the engagement's `passed_adjustment_total_cents` by the adjustment's `amount_cents`. `ACCEPTED`, `REJECTED`, and `PASSED` are all terminal.

### 3.7. Fee and Scope Negotiation

Scope drift is negotiated through fee change requests, which either party may open. Creating one takes an `engagement_id`, a `scope_description` of the change driving the fee impact, and a signed `delta_cents` that must be non-zero (else `ERR_INVALID_FEE_DELTA`); a positive delta is an increase. The server derives `proposed_by_role` from the creator's role — `CONTROLLER_OFFICE` when a `Controller` proposes, `AUDITOR` when an `ExternalAuditor` proposes — and the request starts in `PROPOSED`. The list filters by `engagement_id` and `status`.

Resolution is deliberately counter-partisan: the party that proposed a change cannot approve it. Resolving takes a payload `decision` of `APPROVE` or `REJECT` and requires the request to be in `PROPOSED` (`ERR_FEE_CHANGE_NOT_PROPOSED`). When `proposed_by_role` is `CONTROLLER_OFFICE`, the resolver's `X-User-Role` must be `ExternalAuditor`; when it is `AUDITOR`, the resolver must be a `Controller`. A same-party resolution is rejected with `ERR_FEE_CHANGE_SELF_APPROVAL`. Approval carries a fiscal floor: the engagement's `total_fee_cents` plus the request's `delta_cents` must remain greater than zero, or the resolution is rejected with `ERR_FEE_WOULD_GO_NONPOSITIVE`. An approved request becomes `APPROVED` and the engagement's `total_fee_cents` increments by `delta_cents` (with the read-time provisional/final behavior of §2.7); a rejected one becomes `REJECTED` with no fee impact. Either way the outcome is terminal.

Withdrawal is the proposer's escape hatch: from `PROPOSED` (else `ERR_FEE_CHANGE_NOT_PROPOSED`), the acting role must match the original proposer role — a mismatch is rejected with `ERR_FEE_CHANGE_NOT_PROPOSER` — and the request lands on `WITHDRAWN`. Recall from §3.1 and §3.8 that engagement cancellation and representation-letter signing both sweep every still-`PROPOSED` request to `WITHDRAWN` automatically.

### 3.8. Closing Out: Fieldwork Completion, the Representation Letter, and Report Issuance

Closing begins when the auditor judges the evidence complete. Completing fieldwork — an `ExternalAuditor` action moving the engagement from `FIELDWORK` to `FIELDWORK_COMPLETE` — demands a clean desk: the engagement must be in `FIELDWORK` (`ERR_ENGAGEMENT_NOT_IN_FIELDWORK`), no PBC request may remain in `OPEN`, `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` (`ERR_UNRESOLVED_PBC_REQUESTS`), and no query may remain in `OPEN`, `AWAITING_CLIENT`, or `ESCALATED` (`ERR_UNRESOLVED_QUERIES`). Success recomputes the engagement's `posture` to `CLOSING`.

The management representation letter formalizes management's assertions. A `Preparer` creates the draft — one letter per engagement — with an `engagement_id`; it starts in `DRAFT`, and the list filters by `engagement_id`. Submitting the draft for signature is a `Preparer` action requiring the letter to be in `DRAFT` (`ERR_REP_LETTER_NOT_DRAFT`) and the engagement to be in `FIELDWORK_COMPLETE` (`ERR_ENGAGEMENT_NOT_CLOSING`); it records the submitter's `X-User-ID` as `prepared_by_user_id` and moves the letter to `PENDING_SIGNATURE`.

Signing is the `Controller`'s act and the engagement's point of no return. The letter must be in `PENDING_SIGNATURE` (`ERR_REP_LETTER_NOT_PENDING`), and segregation of duties forbids the signer from being the drafter: if `X-User-ID` equals `prepared_by_user_id`, the signing is rejected with `ERR_REP_LETTER_SOD_VIOLATION`. As detailed in §2.9, the request must also carry `expected_engagement_version`. Signing records `signed_by_user_id`, stamps `signed_at` from the logical clock, moves the letter to its terminal `SIGNED` state, recomputes the engagement's `posture` to `LOCKED`, increments the engagement's `version` by one, and cascades: every PBC request in `OPEN`, `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` becomes `FROZEN`; every `PENDING_REVIEW` evidence upload becomes `INVALIDATED`; and every `PROPOSED` fee change request becomes `WITHDRAWN`.

Issuing the report is the final transition, from `FIELDWORK_COMPLETE` to the terminal `REPORT_ISSUED`, performed by an `ExternalAuditor`. Three gates guard it, in the precedence order of §2.10: the engagement must be in `FIELDWORK_COMPLETE` (`ERR_ENGAGEMENT_NOT_CLOSING`); the representation letter must be `SIGNED` (`ERR_REP_LETTER_NOT_SIGNED`); and the passed-adjustment total must clear materiality — `passed_adjustment_total_cents`, the sum of `amount_cents` over the engagement's `PASSED` adjustments, must be strictly less than the engagement's `materiality_cents`. Equality does not pass: a total exactly equal to materiality is rejected with `ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY` just as an overage is. Because the threshold check happens only here, passing an adjustment in §3.6 is never blocked by the running total. Issuance recomputes `posture` to `LOCKED` and leaves the engagement in its terminal `REPORT_ISSUED` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state-transition action — return `200 OK`; the clock-setting operation also returns `200 OK`. The table below is a summary only: request payloads, response bodies, and side effects are defined by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock to a supplied instant | Controller |
| POST | `/api/audit-engagements` | Create a new audit engagement | Controller |
| GET | `/api/audit-engagements` | List engagements (paginated) | Controller, Preparer, ExternalAuditor |
| GET | `/api/audit-engagements/{id}` | Get one engagement | Controller, Preparer, ExternalAuditor |
| POST | `/api/audit-engagements/{id}/commence-fieldwork` | Move engagement from PLANNING to FIELDWORK | Controller |
| POST | `/api/audit-engagements/{id}/complete-fieldwork` | Move engagement from FIELDWORK to FIELDWORK_COMPLETE | ExternalAuditor |
| POST | `/api/audit-engagements/{id}/issue-report` | Issue the final audit report | ExternalAuditor |
| POST | `/api/audit-engagements/{id}/cancel` | Cancel the engagement and cascade to children | Controller |
| POST | `/api/locations` | Register an audit location | Controller |
| GET | `/api/locations` | List locations, filterable by engagement | Controller, Preparer, ExternalAuditor |
| GET | `/api/locations/{id}` | Get one location | Controller, Preparer, ExternalAuditor |
| POST | `/api/pbc-requests` | Add a PBC request to an engagement | ExternalAuditor |
| GET | `/api/pbc-requests` | List PBC requests with optional filters | Controller, Preparer, ExternalAuditor |
| GET | `/api/pbc-requests/{id}` | Get one PBC request | Controller, Preparer, ExternalAuditor |
| POST | `/api/pbc-requests/{id}/submit` | Mark a PBC request as submitted for review | Preparer |
| POST | `/api/pbc-requests/{id}/review` | Record the auditor's accept/reject decision | ExternalAuditor |
| POST | `/api/pbc-requests/{id}/evidence-uploads` | Upload a new evidence version (OCC-guarded) | Preparer |
| GET | `/api/evidence-uploads` | List evidence uploads with optional filters | Controller, Preparer, ExternalAuditor |
| GET | `/api/evidence-uploads/{id}` | Get one evidence upload | Controller, Preparer, ExternalAuditor |
| POST | `/api/queries` | Raise an auditor query | ExternalAuditor |
| GET | `/api/queries` | List queries with optional filters | Controller, Preparer, ExternalAuditor |
| GET | `/api/queries/{id}` | Get one query | Controller, Preparer, ExternalAuditor |
| POST | `/api/queries/{id}/route-to-client` | Route a query to the client | ExternalAuditor |
| POST | `/api/queries/{id}/respond` | Respond to a routed query | Preparer |
| POST | `/api/queries/{id}/escalate` | Escalate an open or awaiting-client query | ExternalAuditor |
| POST | `/api/queries/{id}/close` | Close a responded or escalated query | ExternalAuditor |
| POST | `/api/sampling-requests` | Create a sampling request | ExternalAuditor |
| GET | `/api/sampling-requests` | List sampling requests with optional filters | Controller, Preparer, ExternalAuditor |
| GET | `/api/sampling-requests/{id}` | Get one sampling request | Controller, Preparer, ExternalAuditor |
| POST | `/api/sampling-requests/{id}/dispatch` | Dispatch a sampling request (overlap-checked) | ExternalAuditor |
| POST | `/api/sampling-requests/{id}/start` | Mark sampling in progress | Preparer |
| POST | `/api/sampling-requests/{id}/complete` | Mark sampling complete | Preparer |
| POST | `/api/sampling-requests/{id}/cancel` | Cancel a sampling request | ExternalAuditor |
| POST | `/api/fieldwork-visits` | Schedule a fieldwork visit | ExternalAuditor |
| GET | `/api/fieldwork-visits` | List fieldwork visits with optional filters | Controller, Preparer, ExternalAuditor |
| GET | `/api/fieldwork-visits/{id}` | Get one fieldwork visit | Controller, Preparer, ExternalAuditor |
| POST | `/api/fieldwork-visits/{id}/complete` | Mark a visit completed | ExternalAuditor |
| POST | `/api/fieldwork-visits/{id}/cancel` | Cancel a visit | ExternalAuditor |
| POST | `/api/adjustments` | Propose an audit adjustment | ExternalAuditor |
| GET | `/api/adjustments` | List adjustments (incl. the passed-adjustment schedule) | Controller, Preparer, ExternalAuditor |
| GET | `/api/adjustments/{id}` | Get one adjustment | Controller, Preparer, ExternalAuditor |
| POST | `/api/adjustments/{id}/disposition` | Disposition a proposed adjustment | Controller |
| POST | `/api/representation-letters` | Create the draft representation letter | Preparer |
| GET | `/api/representation-letters` | List representation letters, filterable by engagement | Controller, Preparer, ExternalAuditor |
| GET | `/api/representation-letters/{id}` | Get one representation letter | Controller, Preparer, ExternalAuditor |
| POST | `/api/representation-letters/{id}/submit` | Submit the draft for signature | Preparer |
| POST | `/api/representation-letters/{id}/sign` | Sign the letter (SoD-checked, OCC-guarded) | Controller |
| POST | `/api/fee-change-requests` | Propose a fee/scope change | Controller, ExternalAuditor |
| GET | `/api/fee-change-requests` | List fee change requests with optional filters | Controller, Preparer, ExternalAuditor |
| GET | `/api/fee-change-requests/{id}` | Get one fee change request | Controller, Preparer, ExternalAuditor |
| POST | `/api/fee-change-requests/{id}/resolve` | Resolve a fee change (counter-party only) | Controller, ExternalAuditor |
| POST | `/api/fee-change-requests/{id}/withdraw` | Withdraw a pending fee change request | Controller, ExternalAuditor |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_PBC_NOT_FOUND` | 404 Not Found |
| `ERR_EVIDENCE_NOT_FOUND` | 404 Not Found |
| `ERR_QUERY_NOT_FOUND` | 404 Not Found |
| `ERR_SAMPLING_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REP_LETTER_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_CHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_ENGAGEMENT_NOT_IN_PLANNING` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_IN_FIELDWORK` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_CLOSING` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ENGAGEMENT_POSTURE_LOCKED` | 409 Conflict |
| `ERR_NO_LOCATIONS_DEFINED` | 409 Conflict |
| `ERR_UNRESOLVED_PBC_REQUESTS` | 409 Conflict |
| `ERR_UNRESOLVED_QUERIES` | 409 Conflict |
| `ERR_REP_LETTER_NOT_SIGNED` | 409 Conflict |
| `ERR_PBC_NOT_OPEN_FOR_UPLOAD` | 409 Conflict |
| `ERR_PBC_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_PBC_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_NO_PENDING_EVIDENCE` | 409 Conflict |
| `ERR_QUERY_NOT_OPEN` | 409 Conflict |
| `ERR_QUERY_NOT_AWAITING_CLIENT` | 409 Conflict |
| `ERR_QUERY_NOT_CLOSABLE` | 409 Conflict |
| `ERR_SAMPLING_NOT_DRAFT` | 409 Conflict |
| `ERR_SAMPLING_NOT_DISPATCHED` | 409 Conflict |
| `ERR_SAMPLING_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_SAMPLING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_VISIT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ADJUSTMENT_NOT_PROPOSED` | 409 Conflict |
| `ERR_REP_LETTER_NOT_DRAFT` | 409 Conflict |
| `ERR_REP_LETTER_NOT_PENDING` | 409 Conflict |
| `ERR_FEE_CHANGE_NOT_PROPOSED` | 409 Conflict |
| `ERR_RATIONALE_REQUIRED` | 400 Bad Request |
| `ERR_REP_LETTER_SOD_VIOLATION` | 403 Forbidden |
| `ERR_FEE_CHANGE_SELF_APPROVAL` | 403 Forbidden |
| `ERR_FEE_CHANGE_NOT_PROPOSER` | 403 Forbidden |
| `ERR_NOT_REQUEST_OWNER` | 403 Forbidden |
| `ERR_INVALID_EVIDENCE_FILE` | 400 Bad Request |
| `ERR_INVALID_HASH` | 400 Bad Request |
| `ERR_INVALID_SAMPLING_WINDOW` | 400 Bad Request |
| `ERR_INVALID_SAMPLE_SIZE` | 400 Bad Request |
| `ERR_INVALID_ADJUSTMENT_AMOUNT` | 400 Bad Request |
| `ERR_INVALID_FEE_DELTA` | 400 Bad Request |
| `ERR_NO_SAMPLING_LOCATIONS` | 400 Bad Request |
| `ERR_INVALID_VISIT_WINDOW` | 400 Bad Request |
| `ERR_SAMPLING_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_VISIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_LOCATION_MATERIALITY_TOO_HIGH` | 422 Unprocessable Entity |
| `ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY` | 402 Payment Required |
| `ERR_FEE_WOULD_GO_NONPOSITIVE` | 402 Payment Required |
| `ERR_DEADLINE_AFTER_FILING` | 422 Unprocessable Entity |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 Precondition Failed |
