# Trademark Watch Enforcement API — Product Requirements Document

## 1. Introduction

Brand protection counsel live and die by deadlines. A watch service flags a confusingly similar application on a Tuesday; the opposition window closes thirty days after publication; a cease-and-desist goes unanswered; a coexistence agreement is breached two years later and the settled matter has to be reopened, the letter reissued, and a fresh response deadline docketed — all without losing track of who drafted what, who verified it, and how much of the client's enforcement budget remains. The Trademark Watch Enforcement API exists to make that entire practice auditable and machine-enforceable: watch-alert intake with likelihood-of-confusion scoring, opposition and cancellation docketing, cease-and-desist correspondence with segregation of duties, marketplace and domain takedowns, coexistence negotiation with round caps, use-evidence collection for maintenance filings, clearance searches for candidate marks, and counterfeit referral with customs recordation.

The system is built around three commitments. First, fiscal discipline: every letter issued and every takedown filed accrues fees against a fixed client budget, and the ledger must reconcile after every forward and compensating action. Second, segregation of duties: the associate who drafts a letter may never approve it, the paralegal who dockets a deadline may never verify it, and the staffer who collects a use specimen may never verify it. Third, a single logical clock drives every statutory computation — opposition windows, business-day response deadlines, maintenance windows and grace periods, agreement terms, and recordation expiries — so that time-based behavior is deterministic and testable rather than hostage to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their capacity. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role must appear in the endpoint's authorized role list, or the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles are recognized, spelled exactly as follows:

- `PlatformAdmin` — operations administrator; creates clients and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- `Paralegal` — docketing and intake staff; triages alerts, publishes and registers records, dockets and extends deadlines, collects evidence, files takedowns, records letter responses, prepares and submits maintenance filings, claims agreement breaches, and creates customs recordations. When `X-User-Role` is `Paralegal`, `X-User-ID` is an opaque operator identifier; the server records it (for example, as `docketed_by_user_id` on a docketed deadline or `collected_by_user_id` on a collected specimen) but does not compare it to any entity's `id`.
- `AssociateAttorney` — junior counsel; assesses and escalates alerts, drafts and issues letters, negotiates agreements, disposes clearance hits, and creates manual counterfeit referrals. When `X-User-Role` is `AssociateAttorney`, `X-User-ID` is an opaque operator identifier recorded on the work product (for example, `drafted_by_user_id` on a drafted letter) but not compared to any entity's `id`.
- `PartnerAttorney` — senior counsel; approves letters, resolves and reopens matters, executes agreements, decides office actions, finalizes clearances, refers referrals, and late-satisfies deadlines. When `X-User-Role` is `PartnerAttorney`, `X-User-ID` is an opaque operator identifier recorded where the scaffold of a transition writes it (for example, `approved_by_user_id` on approval) but not compared to any entity's `id`.
- `ClientContact` — a brand-owner contact. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's `client_id` field to `X-User-ID`. A `ClientContact` may only access resources whose `client_id` equals their `X-User-ID`; touching another client's resource is rejected with `ERR_FORBIDDEN`.
- `WatchService` — an external watch-service integration permitted only to submit alert intake batches. When `X-User-Role` is `WatchService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Segregation of duties is enforced by identity comparison on specific transitions rather than by role: the caller approving or sending back a letter must differ from its `drafted_by_user_id`; the caller verifying a deadline must differ from its `docketed_by_user_id`; the caller verifying an evidence item must differ from its `collected_by_user_id`. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- A request to an undeclared path, or a declared path with an undeclared method, is rejected with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope. A malformed JSON body is rejected with `ERR_VALIDATION` (HTTP 400). An unexpected server fault is rejected with `ERR_INTERNAL` (HTTP 500) in the same envelope.
- The `api_request_timestamp` in every response's `meta` is read from the logical clock of §2.5, not from wall-clock time.

### 2.3. Pagination

List endpoints accept two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit` is less than `total_count`. A boolean-typed filter query parameter (such as `auto_created`) parses the values `true`, `1`, and `yes` case-insensitively as true and anything else as false.

### 2.4. Common Resource Properties

Every resource in this system — clients, trademark records, watch alerts, enforcement matters, deadlines, cease-and-desist letters, takedown filings, coexistence agreements, evidence items, maintenance filings, clearance searches, customs recordations, and counterfeit referrals — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation; it is read from the logical clock of §2.5, not wall-clock time.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, likewise from the logical clock.
- `version` (integer): starts at 1 on creation and increments by one on every mutation, including mutations caused by system cascades and clock sweeps.

Because cascades and sweeps mutate resources without a client request on that specific resource, observers must treat `version` and `updated_at` as capable of advancing at any time.

### 2.5. The Logical Clock and Time-Based Sweep

All statutory and term-based reasoning runs against a single server-side logical clock, never wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`. A `PlatformAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant — any valid instant is accepted, including one earlier than the current reading — and the 200 response body is `{"current_utc": <the new instant>}` in the standard envelope; the clock never falls back to wall-clock time afterward. Every clock set runs the full time-based sweep at the new instant, in whatever order the engine chooses, covering: deadlines whose `computed_due_at` has passed flipping to `MISSED`; registered records entering `MAINTENANCE_DUE` and, eventually, cancellation past the grace close; executed agreements entering `MONITORING`, expiring at their term end, and terminating past an uncured cure deadline; and recordations expiring past their term end. Each resource mutated by a sweep has its `updated_at` refreshed and `version` incremented as usual. Computed statutory datetime fields (such as `opposition_due_at`, `computed_due_at`, `response_due_at`, the maintenance horizons, and term bounds) are rendered as ISO 8601 UTC; when the computed value lands on a whole second the fractional part is omitted (for example `2026-08-14T09:00:00Z`), and sub-second values keep three fractional digits.

### 2.6. Monetary Precision and the Enforcement Budget Ledger

All monetary values are integer cents; no fractional cents are ever stored. Where a calculation can produce a fractional cent, it is rounded half-up to whole cents at the step the calculation specifies, and only there. A client is created with a fixed `enforcement_budget_cents` that is immutable after creation. Two computed balances track consumption: `budget_spent_cents` (fees accrued by issued or reissued cease-and-desist letters and by filed takedown filings) and `budget_remaining_cents` (the budget minus the spend). The ledger invariant is absolute: after every forward action (letter issue, letter reissue, takedown filing) and every compensating action (rescinding an issued letter), `budget_spent_cents` plus `budget_remaining_cents` equals `enforcement_budget_cents` exactly.

Letter issuance accrues a flat fee of 75000 cents; each reissue — manual or cascade-driven — accrues 25000 cents. Takedown filing fees depend on the platform: 15000 cents for `AMAZON`, 12000 for `EBAY`, 18000 for `ALIBABA`, 9000 for `META`, and 25000 for `DOMAIN_REGISTRAR`; the fee is computed at draft time onto the filing's `fee_cents` and accrued when the filing is filed. Letter fees additionally accumulate onto the owning matter's `accrued_fees_cents` and are not reversed unless the letter is voided from `ISSUED`. Forward fee actions check affordability against `budget_remaining_cents` and are rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422) when the remaining budget would not cover the fee; reissues driven by the breach cascade bypass this affordability check, as does the fee accrual they cause.

### 2.7. Portfolio Exposure Index and Watch Posture

Each client carries a computed `exposure_index`: the sum, over all of the client's enforcement matters currently in `ACTIVE` status, of a per-matter weight — 10 for `OPPOSITION`, 15 for `CANCELLATION`, 20 for `INFRINGEMENT`, and 25 for `COUNTERFEIT` — with the weight of any matter in `JEOPARDY` posture multiplied by one and a half. The raw sum is rounded half-up to a whole integer exactly once, at the end; per-matter rounding is never applied. Resolved matters contribute nothing. The client's `watch_posture` is `ELEVATED` whenever the index is at least 100 and `STANDARD` otherwise. The index and posture are recomputed whenever a matter is created by escalation, resolved, or reopened, and whenever any linked deadline flips to `MISSED` or is satisfied late.

### 2.8. Statutory Date Computation Variants

Two computation variants govern every due-date arithmetic in the system, and both preserve the time-of-day of the anchor instant:

- `CALENDAR_ROLL_FORWARD` counts calendar days from the basis date and then, while the resulting instant falls on a Saturday or Sunday (in UTC), rolls it forward one calendar day at a time until it lands on a weekday. A Friday basis with a five-day offset therefore lands on the following Wednesday with no roll needed. This variant applies to `OPPOSITION_WINDOW` and `RENEWAL` deadlines and to the record's `opposition_due_at`.
- `BUSINESS_DAY_COUNT` counts only business days, excluding the basis day itself: starting from the basis, advance one calendar day at a time, incrementing the count only for Monday-through-Friday days, until the count reaches the offset. For an identical basis and offset this produces a later due instant than calendar counting whenever a weekend intervenes. This variant applies to `RESPONSE_DUE`, `OFFICE_ACTION`, and `CUSTOM` deadlines and to the letter's `response_due_at`.

The computation variant of a deadline is derived from its `deadline_type` at docketing — it is never supplied by the caller — and extensions reuse the deadline's own variant, treating the current `computed_due_at` as the new basis. Calendar arithmetic elsewhere in the system (the five- and six-year maintenance horizons, the six-month grace period, the ten-year horizon advances, and the recordation buffer gap) adds whole years or months with clamping: a February 29 anchor becomes February 28 in a non-leap target year, and a month-level shift clamps the day to the last day of the target month.

### 2.9. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and no other endpoint takes a version field. Recording an assessment against a watch alert requires the request to carry `expected_watch_alert_version` holding the alert's `version` as the caller last observed it; each accepted assessment legitimately supersedes the current `final_score` and `final_tier` and increments the alert's `version` by one, so a caller working from a stale read would silently overwrite a newer attorney's assessment. Proposing terms on a coexistence agreement likewise requires `expected_agreement_version` matching the agreement's current `version`; each accepted proposal supersedes the outstanding terms and increments the agreement's `version` by one. An expected-version field must be an integer; a string of decimal digits is tolerated and coerced to an integer, and any other type is `ERR_VALIDATION`. In both cases, a mismatch with the entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires an expected-version field.

### 2.10. Validation Pipeline and Priority Ordering

Every request is validated against an ordered pipeline; an earlier failure masks later ones, so callers always see the highest-priority applicable error. The order is:

1. **Authentication** — `X-User-Role` and `X-User-ID` present and the role declared, else `ERR_UNAUTHENTICATED`.
2. **Schema** — the request body satisfies the endpoint's input schema: required fields present, no unknown fields, enum values valid, assessment weights summing to 1.0, and seizure-line entries positive integers, else `ERR_VALIDATION`. (An out-of-range `hit_index` is also `ERR_VALIDATION` but is evaluated against the target search's hits, so it surfaces at existence time — after the search is known to exist and before its `OPEN` state is checked — rather than at this step.)
3. **Authorization** — the caller's role is in the endpoint's role list; `ClientContact` scope is respected; late satisfaction from `MISSED` is attempted only by a `PartnerAttorney`, else `ERR_FORBIDDEN`.
4. **Existence** — path identifiers exist, validated left to right, and body-referenced foreign keys (`client_id`, `enforcement_matter_id`, every element of `evidence_item_ids`, `supersedes_recordation_id`) exist, else `ERR_NOT_FOUND`.
5. **State** — the target entity is in a state from which the requested transition is declared, including terminal-state lockdown, else `ERR_INVALID_STATE`.
6. **Optimistic concurrency** — the expected-version field matches, else `ERR_STALE_VERSION`.
7. **Segregation of duties** — else `ERR_SEGREGATION_OF_DUTIES`.
8. **Enforcement bar** — a live coexistence agreement barring letter issuance surfaces `ERR_ENFORCEMENT_BARRED`.
9.–11. **Temporal rules**, in order: the opposition window (`ERR_OPPOSITION_WINDOW_CLOSED`), the maintenance filing window (`ERR_OUTSIDE_FILING_WINDOW`), and the litigation-escalation response window (`ERR_RESPONSE_WINDOW_OPEN`).
12.–13. **Score gates**: the escalation threshold (`ERR_SCORE_BELOW_THRESHOLD`) precedes the dismissal cap (`ERR_SCORE_ABOVE_DISMISS_CAP`).
14.–19. **Business constraints**, in order: agreement overlap (`ERR_AGREEMENT_OVERLAP`), the recordation buffer gap (`ERR_RECORDATION_GAP_VIOLATION`), the three cap family (`ERR_ROUND_CAP_REACHED`, `ERR_APPEAL_CAP_REACHED`, `ERR_EXTENSION_CAP_REACHED`), unresolved clearance hits (`ERR_UNRESOLVED_HITS`), pending-deadline and matter-not-active blocks (`ERR_PENDING_DEADLINES`, `ERR_MATTER_NOT_ACTIVE`), and the manual referral threshold (`ERR_REFERRAL_THRESHOLD_NOT_MET`).
20.–22. **Referential business rules**, in order: record registration state (`ERR_RECORD_NOT_REGISTERED`), the evidence-integrity family (`ERR_CLASS_NOT_ON_RECORD`, `ERR_EVIDENCE_RECORD_MISMATCH`, `ERR_EVIDENCE_NOT_VERIFIED`, `ERR_EVIDENCE_STALE`, `ERR_INCOMPLETE_CLASS_COVERAGE`), and the customs-recordation requirement for seizure referrals (`ERR_CUSTOMS_RECORDATION_REQUIRED`).
23. **Fiscal** — affordability of the fee being accrued, else `ERR_BUDGET_EXCEEDED`.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Budget Initialization

A `PlatformAdmin` onboards a brand owner by creating a client with its legal `name`, its `industry` vertical, and a total `enforcement_budget_cents` — all three required, `name` and `industry` strings and `enforcement_budget_cents` an integer greater than or equal to zero. The budget figure is fixed for the life of the client; it cannot be amended afterward. At creation the ledger fields initialize themselves: `budget_spent_cents` starts at zero, `budget_remaining_cents` starts equal to `enforcement_budget_cents`, `exposure_index` starts at zero, and `watch_posture` starts `STANDARD`. Client reads are available to every internal role and to the owning `ClientContact`.

### 3.2. Portfolio Registration and the Record Lifecycle

With a client in place, a `Paralegal` — or a `ClientContact` acting for their own `client_id` — registers a portfolio mark by supplying the `mark_text`, a `mark_type` of `WORD`, `DESIGN`, or `COMPOSITE`, a `jurisdiction` code string (its length and format are not validated), the `nice_classes` covered (an array of Nice classification integers, each from 1 to 45, with at least one entry required), and the office's `application_number`. The record is born in `APPLICATION_PENDING` status with `verified_evidence_count` at zero, and `publication_date`, `registration_date`, `opposition_due_at`, and all three maintenance horizons null. Records can be listed with optional `client_id` and `status` filters alongside the standard `limit` and `offset`.

Publication is a `Paralegal` action carrying the official `publication_date`; it moves the record from `APPLICATION_PENDING` to `PUBLISHED` and computes `opposition_due_at` as thirty calendar days after publication, rolled forward past any Saturday or Sunday under the `CALENDAR_ROLL_FORWARD` variant. Registration, also by a `Paralegal`, carries the `registration_date` and moves the record from `PUBLISHED` to `REGISTERED`, computing the three maintenance horizons: `maintenance_window_open` five years after registration, `maintenance_window_close` six years after registration, and `maintenance_grace_close` six months beyond the window close.

From then on the record's fate is entangled with enforcement activity. Escalating an alert into an `OPPOSITION` matter flips a `PUBLISHED` record to `UNDER_CHALLENGE`; escalating into a `CANCELLATION` matter does the same to a `REGISTERED` record. Resolution cascades back: a `FAVORABLE` or `SETTLED` outcome on an opposition matter returns the record to `PUBLISHED`, the same outcomes on a cancellation matter return it to `REGISTERED`, and an `ADVERSE` outcome on either matter type cancels the record outright. Cancellation is terminal and moots everything attached to the record: every watch alert of the record in `ESCALATED` moves to `DISMISSED`, every customs recordation in `ACTIVE` moves to `REVOKED`, and every coexistence agreement in `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or `CURE_PERIOD` moves to `TERMINATED`.

Time acts on records too. When the logical clock reaches `maintenance_window_open`, a `REGISTERED` record enters `MAINTENANCE_DUE`. If a maintenance filing of the record is accepted, the record returns to `REGISTERED` and all three maintenance horizons advance by ten years. If the clock passes `maintenance_grace_close` with no filing of the record in `SUBMITTED`, `LATE_FILED`, or `ACCEPTED`, the record is cancelled by the sweep, triggering the same moot cascade as an adverse challenge.

### 3.3. Watch Alert Intake and Likelihood-of-Confusion Scoring

Alerts enter the system through watch-service batches or manual entry; both the `WatchService` integration and a `Paralegal` may submit intake. The payload names the watched portfolio mark via `trademark_record_id`, the `source` (`WATCH_SERVICE`, `MANUAL`, or `MARKETPLACE_SWEEP`), the incoming `conflicting_mark_text` and `conflicting_owner`, the `conflicting_classes` of the third-party mark (an array of integers; no 1–45 Nice-class bound is enforced on them), and three integer similarity readings each bounded inclusively between 0 and 100: `similarity_mark`, `similarity_goods`, and `similarity_channels`.

Intake computes a provisional confusion score with fixed weights: half the mark similarity, three-tenths the goods similarity, and two-tenths the channel similarity are summed, the raw sum is rounded half-up to two decimal places, and — because the provisional variant carries no fame adjustment — the result is clamped into the 0-to-100 band. An identical-presumption floor then applies: when both `similarity_mark` and `similarity_goods` are at least 90, the score is raised to at least 85. The result is stored on `provisional_score` and bucketed into `provisional_tier`: `HIGH` at 70 or above, `MEDIUM` at 40 or above, otherwise `LOW`. The alert starts in `NEW` status with `assessment_round` at zero, `escalation_level` at `STANDARD`, `confirmed_counterfeit_count` at zero, `referral_auto_created` false, and `final_score`/`final_tier` null until the first assessment. The alert listing supports `trademark_record_id`, `status`, and `final_tier` filters.

A `Paralegal` triages a `NEW` alert into `TRIAGED`. From `TRIAGED` an `AssociateAttorney` records an attorney assessment, moving the alert to `UNDER_ASSESSMENT`; the same assessment action also loops an `UNDER_ASSESSMENT` alert back into `UNDER_ASSESSMENT` (superseding the prior result) and re-opens a `MONITORING` alert into `UNDER_ASSESSMENT` for re-assessment. Every assessment carries the attorney's own `weight_mark`, `weight_goods`, and `weight_channels` — each a number (integer or floating point), and the three must sum to 1.0 within a tolerance of 0.0001, meaning an absolute deviation of exactly 0.0001 is still accepted — an integer `fame_adjustment` between -20 and 20 inclusive, a free-text `rationale`, and the OCC field `expected_watch_alert_version`. The assessed variant replaces the fixed weights with the attorney's: the weighted sum is rounded half-up to two decimal places, the fame adjustment is added, the result is clamped to the 0-to-100 band, the identical-presumption floor at 85 applies on the same dual-similarity condition, and the tier is bucketed with the same 70/40 cutoffs. Each accepted assessment increments `assessment_round` by one, recomputes and stores `final_score` and `final_tier`, and increments the alert's `version` by one — so identical similarity triples generally yield a different assessed score than the provisional one.

Score bands gate the alert's disposition from `UNDER_ASSESSMENT`. An attorney may place the alert into `MONITORING` only when `final_score` is at least 40 but below 70; an attempt outside that band is rejected with `ERR_INVALID_STATE`. Dismissal into `DISMISSED` requires `final_score` below 40 and carries a `dismiss_reason`; an alert scoring 40 or above cannot be dismissed and the attempt is rejected with `ERR_SCORE_ABOVE_DISMISS_CAP`. Escalation is covered in the next subsection. Separately, when the record under an `ESCALATED` alert is cancelled, the moot cascade moves the alert to `DISMISSED` — the alert's terminal state.

### 3.4. Escalation and Enforcement Matter Management

Escalation converts an assessed alert into a live enforcement matter. An `AssociateAttorney` escalates an `UNDER_ASSESSMENT` alert by supplying the `matter_type` — `OPPOSITION`, `CANCELLATION`, `INFRINGEMENT`, or `COUNTERFEIT` — subject to a battery of preconditions. The `final_score` must be at least 70, else `ERR_SCORE_BELOW_THRESHOLD`. The record's state must admit the chosen theory: an opposition requires the record to be `PUBLISHED` (anything else is `ERR_INVALID_STATE`) and the logical clock must not have passed `opposition_due_at` (else `ERR_OPPOSITION_WINDOW_CLOSED`); a cancellation requires the record to be `REGISTERED`; infringement and counterfeit matters require only that the record not be `CANCELLED`.

A successful escalation creates the matter — the response body is the created matter, not the alert — with `client_id`, `trademark_record_id`, and `watch_alert_id` copied from the alert and its record, `matter_type` as supplied, `status` `ACTIVE`, `posture` `NORMAL`, `accrued_fees_cents` and `open_deadline_count` at zero, and `resolution_outcome` null. The alert moves to `ESCALATED`. For opposition and cancellation matters the record challenge cascade described in §3.2 fires in the same breath, and the client's `exposure_index` and `watch_posture` are recomputed. Matters can be listed with `client_id`, `trademark_record_id`, `watch_alert_id`, and `status` filters.

Resolution belongs to a `PartnerAttorney` and requires the matter to have no open deadlines — `open_deadline_count` counts linked deadlines in `DOCKETED`, `PENDING`, or `EXTENDED`, and a nonzero count is rejected with `ERR_PENDING_DEADLINES`. The supplied `outcome` (`FAVORABLE`, `ADVERSE`, or `SETTLED`) is recorded on `resolution_outcome` as the matter moves from `ACTIVE` to `RESOLVED`, the record cascade of §3.2 fires for challenge matters, and client exposure is recomputed.

`RESOLVED` is reopenable — the matter state machine has no hard terminal state. A `PartnerAttorney` may reopen a matter manually, and the coexistence breach cascade of §3.7 reopens it automatically. Either way, `resolution_outcome` is cleared to null, every letter of the matter sitting in `COMPLIED` is reissued back to `ISSUED` — its `reissue_count` incremented by one, `issued_at` set to the current instant, `response_due_at` recomputed, and the 25000-cent reissue fee accrued with the affordability check bypassed — and for each reissued letter the system auto-dockets a fresh `RESPONSE_DUE` deadline anchored at the reissue instant with an offset equal to the letter's `response_due_days`, in `DOCKETED` status with `docketed_by_user_id` recorded as the literal `system`; like every auto-docketed deadline it carries `statutory_basis` null, `extension_count` zero, and the default `max_extensions` of 3. Client exposure is recomputed at the end.

### 3.5. Deadline Docketing, Verification, and the Jeopardy Cascade

Deadlines are docketed onto an `ACTIVE` matter by a `Paralegal` or `AssociateAttorney`; docketing against a matter in any other status is rejected with `ERR_MATTER_NOT_ACTIVE`. The docketing payload carries the `deadline_type` (`OPPOSITION_WINDOW`, `RESPONSE_DUE`, `OFFICE_ACTION`, `RENEWAL`, or `CUSTOM`), a free-text `statutory_basis` citation, the `basis_date` anchoring the count, a strictly positive `offset_days`, and an optional `max_extensions` cap defaulting to 3 — a non-negative integer, so an explicit zero forbids any extension. The server derives `computation_variant` from the deadline type per §2.8, computes `computed_due_at`, and records the caller in `docketed_by_user_id` — or the literal `system` when the deadline was auto-docketed by a letter issue or a reopen cascade. The deadline starts in `DOCKETED` with `extension_count` at zero, `verified_by_user_id` null, `satisfied_at` unset, `satisfied_late` false, and `requires_partner_review` false. Deadlines are listed with `enforcement_matter_id` and `status` filters.

Verification moves a deadline from `DOCKETED` to `PENDING` and is performed by an `AssociateAttorney` or `PartnerAttorney` who must not be the docketing caller; a self-verify is rejected with `ERR_SEGREGATION_OF_DUTIES`, and a successful verify stamps `verified_by_user_id` with the caller. Extensions are a `Paralegal` action available from `PENDING` and from `EXTENDED` itself, carrying `additional_days`; each extension recomputes `computed_due_at` using the deadline's own variant with the current `computed_due_at` as the new basis, and increments `extension_count`. Once `extension_count` reaches `max_extensions`, further extension is rejected with `ERR_EXTENSION_CAP_REACHED`.

Satisfaction has two flavors. From `PENDING` or `EXTENDED`, a timely satisfy by a `Paralegal` (or partner) while the clock is at or before `computed_due_at` stamps `satisfied_at` and leaves `satisfied_late` false; the deadline reaches its terminal `SATISFIED` state. Once the clock sweep has flipped a deadline to `MISSED`, satisfaction becomes a `PartnerAttorney`-only act and the request must explicitly carry `allow_late` set to true; a missing or non-true `allow_late` surfaces `ERR_VALIDATION` before the role check, and only then does a non-`PartnerAttorney` caller surface `ERR_FORBIDDEN`. (`allow_late`, when present on any satisfy call, must be a boolean, else `ERR_VALIDATION`; it is ignored on a timely satisfy.) A late satisfy stamps `satisfied_at`, sets `satisfied_late` true, recomputes the matter's posture (which leaves `JEOPARDY` if no other `MISSED` deadline remains), and recomputes the client's exposure index.

The `MISSED` transition itself belongs to the clock sweep: when the logical clock passes `computed_due_at` on a `PENDING` or `EXTENDED` deadline, the deadline flips to `MISSED` and a jeopardy cascade fires. The owning matter's `posture` becomes `JEOPARDY`; every sibling deadline of the same matter still in `DOCKETED`, `PENDING`, or `EXTENDED` has `requires_partner_review` set true; the matter's originating watch alert has `escalation_level` raised from `STANDARD` to `URGENT`; and the client's `exposure_index` is recomputed with the jeopardy multiplier applied.

### 3.6. Cease-and-Desist Correspondence

Letters are drafted onto an `ACTIVE` matter by an `AssociateAttorney` or `PartnerAttorney`; drafting against a non-active matter is rejected with `ERR_MATTER_NOT_ACTIVE`. The draft captures the `demand_type` (`CEASE_USE`, `CANCEL_REGISTRATION`, or `DELIST_MARKETPLACE`), the `recipient_name` and `recipient_address`, an optional `response_due_days` defaulting to 14 business days (an integer of at least 1 when supplied), an optional `settlement_amount_cents` recording any agreed settlement at draft time (an integer of at least 0 when supplied), and an `installment_count` defaulting to 1 (an integer of at least 1 when supplied). The letter starts in `DRAFT` with `drafted_by_user_id` stamped from the caller, `approved_by_user_id` null, `reissue_count` zero, and the `installment_schedule` not yet computed. Letters can be listed with `enforcement_matter_id` and `status` filters.

An associate or partner submits a `DRAFT` letter for review, moving it to `PENDING_REVIEW`. The approval decision belongs exclusively to a `PartnerAttorney` other than the drafter: a self-approval or self-send-back is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `decision` of `APPROVED` moves the letter to `APPROVED` and stamps `approved_by_user_id`; a decision of `SENT_BACK` returns it to `DRAFT` with no approval stamp.

Issuance by an `AssociateAttorney` is the point of no fiscal return and carries three preconditions beyond state, evaluated in the pipeline order of §2.10: no coexistence agreement on the matter's record may be in `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or `CURE_PERIOD` — a live agreement bars enforcement and the issue is rejected with `ERR_ENFORCEMENT_BARRED`; the matter must still be `ACTIVE`, else `ERR_MATTER_NOT_ACTIVE`; and the client's `budget_remaining_cents` must cover the 75000-cent issuance fee, else `ERR_BUDGET_EXCEEDED`. On issue, `issued_at` is set to the current instant, `response_due_at` is computed as `response_due_days` business days later under `BUSINESS_DAY_COUNT`, the fee accrues to both the matter's `accrued_fees_cents` and the client budget, and the system auto-dockets a `RESPONSE_DUE` deadline anchored at issuance with an offset equal to `response_due_days`, in `DOCKETED` status and `docketed_by_user_id` recorded as `system`, with `statutory_basis` null and the default `max_extensions` of 3.

Response tracking is a `Paralegal` action driven by `response_outcome`. From `ISSUED`, `NEGOTIATION_STARTED` moves the letter to `NEGOTIATING`; from either `ISSUED` or `NEGOTIATING`, `COMPLIED` moves it to `COMPLIED` and `REFUSED` moves it to `REFUSED`. Compliance with a `settlement_amount_cents` set triggers installment computation: the settlement is divided by `installment_count` using floor division to whole cents, and the remainder is added to the final installment, so the `installment_schedule` always sums exactly to the settlement amount. A letter in `NEGOTIATING` can be reissued by an `AssociateAttorney`, optionally overriding `response_due_days` (an integer of at least 1 when supplied; the override is persisted on the letter); the reissue increments `reissue_count`, refreshes `issued_at`, recomputes `response_due_at`, and accrues the 25000-cent reissue fee — subject this time to the affordability check, unlike cascade reissues. A manual reissue does not auto-docket a new deadline.

When talks fail, a `PartnerAttorney` escalates to litigation. From `ISSUED` this is permitted only after `response_due_at` has passed — earlier attempts are rejected with `ERR_RESPONSE_WINDOW_OPEN` — while from `REFUSED` it is always permitted; both land in `ESCALATED_LITIGATION`. Voiding is the compensating path: an `AssociateAttorney` may void a letter in `DRAFT`, `PENDING_REVIEW`, or `APPROVED`, while voiding an `ISSUED` letter is a rescission reserved to a `PartnerAttorney`. Rescission reverses every fee the letter ever accrued — the issuance fee plus the reissue fee times `reissue_count` — crediting both the matter's `accrued_fees_cents` and the client budget by the same amount, restoring the ledger invariant of §2.6. `COMPLIED`, `ESCALATED_LITIGATION`, and `VOID` are the letter's terminal states, with one systematic exception: the breach cascade of §3.7 pulls a `COMPLIED` letter back to `ISSUED` as a reissue.

### 3.7. Marketplace Takedowns, Counterfeit Referrals, and Customs Recordation

A `Paralegal` drafts a takedown filing against a watch alert, naming the `platform` (`AMAZON`, `EBAY`, `ALIBABA`, `META`, or `DOMAIN_REGISTRAR`), the infringing `listing_url`, and the `basis` — `TRADEMARK` or `COUNTERFEIT`. The platform's fee is computed onto `fee_cents` per the §2.6 schedule and the draft sits in `DRAFT`. Filing the draft requires the alert to be in `TRIAGED`, `UNDER_ASSESSMENT`, `MONITORING`, or `ESCALATED` (any other alert state, including `NEW` or `DISMISSED`, is `ERR_INVALID_STATE`), the alert's record to be anything but `CANCELLED`, and the client's remaining budget to cover `fee_cents` (`ERR_BUDGET_EXCEEDED`); on filing, the fee accrues to the client budget. Filings are listed with `watch_alert_id`, `status`, and `basis` filters.

Platform outcomes arrive via the same recording action with an `outcome` of `REMOVED`, `REJECTED`, or `REINSTATED`. A `FILED` or `APPEALED` filing marked `REMOVED` succeeds; when its `basis` is `COUNTERFEIT`, the alert's `confirmed_counterfeit_count` increments by one, and if that count has reached at least 5 while `referral_auto_created` is still false, the threshold cascade auto-creates a counterfeit referral in `DRAFT` status with `auto_created` true, `referral_channel` `LAW_ENFORCEMENT`, an empty `seizure_lines` array, `estimated_damages_cents` zero, `enforcement_matter_id` copied from the alert's `ACTIVE` matter when the alert is `ESCALATED` (otherwise null), and flips `referral_auto_created` to true. `REJECTED` sends a `FILED` or `APPEALED` filing to `REJECTED`. From `REJECTED`, a `Paralegal` may appeal, incrementing `appeal_count`; the appeal cap is 2 and a third attempt is rejected with `ERR_APPEAL_CAP_REACHED`. Reinstatement applies only from `REMOVED` and moves the filing to its terminal `REINSTATED` state, decrementing the alert's `confirmed_counterfeit_count` by one for `COUNTERFEIT` filings, with a floor of zero.

Manual counterfeit referrals are created by an `AssociateAttorney` against an alert whose `confirmed_counterfeit_count` is at least 3 — below that threshold the create is rejected with `ERR_REFERRAL_THRESHOLD_NOT_MET`. The payload supplies the `referral_channel` (`LAW_ENFORCEMENT`, `CUSTOMS_SEIZE`, or `PLATFORM_ESCROW`) and `seizure_lines`, an array whose entries carry `units` and `unit_value_cents`, both required to be positive integers (`ERR_VALIDATION` otherwise). Estimated statutory damages are computed per line: each line's units times unit value times one and a half, rounded half-up to whole cents first, and only then summed into `estimated_damages_cents` — summing raw values and rounding once is deliberately not the rule. A manually created referral has `auto_created` false, starts in `DRAFT`, and copies `enforcement_matter_id` from the alert's `ACTIVE` matter when the alert is `ESCALATED`, otherwise null. A `PartnerAttorney` refers a draft, moving it to `REFERRED`; a `CUSTOMS_SEIZE` referral additionally requires an `ACTIVE` customs recordation on the alert's record, else `ERR_CUSTOMS_RECORDATION_REQUIRED`. Acknowledgement moves a referred referral to its terminal `ACKNOWLEDGED` state. Referrals are listed with `watch_alert_id`, `enforcement_matter_id`, `status`, and `auto_created` filters.

Customs recordation closes the loop. A `Paralegal` records a mark with a customs authority (`US_CBP`, `EU_TAXUD`, or `CN_GACC`) on a record in `REGISTERED` or `MAINTENANCE_DUE` status — any other record state is rejected with `ERR_RECORD_NOT_REGISTERED` — supplying the `recordation_number`, `term_start`, and `term_end`. A buffer-gap rule keeps coverage continuous but never adjacent: for the same record and authority, the new `term_start` must be strictly more than thirty days after every existing non-superseded recordation's `term_end`, else `ERR_RECORDATION_GAP_VIOLATION`. Supplying `supersedes_recordation_id` waives the gap rule and flips the named recordation from `ACTIVE` to `RENEWED`, recording a renewal chain. Recordations begin `ACTIVE`; the clock sweep moves them to `EXPIRED` once the clock passes `term_end`, and the record-cancellation moot cascade moves them to `REVOKED`. Recordations are listed with `trademark_record_id`, `customs_authority`, `status`, and `supersedes_recordation_id` filters — the last of which finds renewals superseding a given recordation.

### 3.8. Coexistence Agreements and the Breach Cascade

An `AssociateAttorney` drafts a coexistence agreement on a record, supplying the `counterparty_name`, the `territory_codes` covered (an array of strings), the `effective_start` (inclusive lower bound of a half-open term) and `effective_end` (exclusive upper bound), an optional `cure_period_days` defaulting to 30 (a non-negative integer when supplied), and an optional `enforcement_matter_id` naming the settling matter to be reopened on breach. The agreement starts in `DRAFT` with `round_count` zero and `current_terms_text`, `breach_claimed_at`, and `cure_deadline` null. Agreements are listed with `trademark_record_id`, `enforcement_matter_id`, and `status` filters.

Negotiation alternates proposals and counters. Proposing terms carries `terms_text` plus the OCC field `expected_agreement_version`: from `DRAFT` the first proposal sets `round_count` to 1; from `COUNTERED` a further proposal requires `round_count` below 8 — the round cap, whose breach is rejected with `ERR_ROUND_CAP_REACHED` — and increments it. Either way the proposal moves the agreement to `PROPOSED`, replaces `current_terms_text`, and increments the agreement's `version` by one. Countering carries `counter_terms_text`, moves `PROPOSED` to `COUNTERED`, replaces `current_terms_text`, and likewise consumes a round. A `PartnerAttorney` executes from `PROPOSED` or `COUNTERED` once two guards pass: the record must be `PUBLISHED`, `REGISTERED`, or `UNDER_CHALLENGE` (else `ERR_INVALID_STATE`), and no other agreement on the same record may be live — in `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or `CURE_PERIOD` — with an intersecting territory set and an overlapping half-open term; mere adjacency, where the new term starts exactly when the existing one ends, is allowed. An overlap is rejected with `ERR_AGREEMENT_OVERLAP`. From execution onward, the live agreement bars cease-and-desist issuance on that record per §3.6, until the bar lifts on expiry or termination.

The clock sweep moves an `EXECUTED` agreement to `MONITORING` once its `effective_start` arrives, and from `MONITORING` to `EXPIRED` once `effective_end` arrives, lifting the enforcement bar. Breach handling is the deep cascade. A `Paralegal` alleges breach on a `MONITORING` agreement with `breach_notes`; `breach_claimed_at` is stamped and, when `enforcement_matter_id` names a `RESOLVED` matter, the cascade runs three levels deep: the matter reopens to `ACTIVE` exactly as in §3.4, every `COMPLIED` letter of that matter is reissued to `ISSUED` with its count bumped and the reissue fee accrued while the affordability check is bypassed, and each reissued letter gets a freshly auto-docketed `RESPONSE_DUE` deadline with `docketed_by_user_id` recorded as `system`.

Cure is decided by a `PartnerAttorney` via `cure_action`. `GRANT` moves `BREACH_ALLEGED` to `CURE_PERIOD` and sets `cure_deadline` to `breach_claimed_at` plus `cure_period_days` calendar days. `CONFIRM_CURED` from `CURE_PERIOD` returns the agreement to `MONITORING` and clears `cure_deadline` to null. If the clock passes `cure_deadline` first, the sweep terminates the agreement — the bar lifts. The record-cancellation moot cascade terminates a live agreement from `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or `CURE_PERIOD` as well. `TERMINATED` and `EXPIRED` are the agreement's terminal states.

### 3.9. Use Evidence, Maintenance Filings, and Portfolio Clearance

Maintenance of a registration runs on verified use evidence. A `Paralegal` or `AssociateAttorney` collects a specimen against a record, naming the `nice_class` it supports — which must be one of the record's own `nice_classes`, else `ERR_CLASS_NOT_ON_RECORD` — a `specimen_type` of `LABEL`, `SCREENSHOT`, `PACKAGING`, or `ADVERTISING`, and the `specimen_date` evidencing use. The item starts `COLLECTED` with `collected_by_user_id` stamped and `verified_by_user_id` null. Verification, by an `AssociateAttorney` or `PartnerAttorney` other than the collector, moves the item to `VERIFIED`, stamps `verified_by_user_id`, and recomputes the record's `verified_evidence_count`; a self-verify draws `ERR_SEGREGATION_OF_DUTIES`. Rejection, with a `reason`, moves an item from `COLLECTED` or `VERIFIED` to its terminal `REJECTED` state and recomputes the count — a rejection from `VERIFIED` is the compensating action that decrements it. Evidence is listed with `trademark_record_id` and `status` filters.

A `Paralegal` prepares a maintenance filing on a record, choosing a `filing_type` of `SECTION_8` or `RENEWAL` and listing the `evidence_item_ids` relied on (each must name an existing evidence item, else `ERR_NOT_FOUND`); the filing starts `PREPARED` with its fees computed on the assumption of a timely submission — `late_fee_cents` zero and `is_late` false. Submission re-finalizes the fees and is governed by the maintenance horizons. The record must be `REGISTERED` or `MAINTENANCE_DUE` (`ERR_RECORD_NOT_REGISTERED`); when the record carries no maintenance horizons at all (it was never registered), the window test does not apply and `ERR_RECORD_NOT_REGISTERED` surfaces directly. Submission within the closed interval from `maintenance_window_open` through `maintenance_window_close` inclusive lands the filing in `SUBMITTED`; submission after the window close but at or before `maintenance_grace_close` lands it in `LATE_FILED`; anything earlier or later is `ERR_OUTSIDE_FILING_WINDOW`. Every listed evidence item must belong to this record (`ERR_EVIDENCE_RECORD_MISMATCH`), be `VERIFIED` (`ERR_EVIDENCE_NOT_VERIFIED`), and bear a `specimen_date` no earlier than 36 months before `maintenance_window_close` (`ERR_EVIDENCE_STALE`); and every Nice class of the record must be covered by at least one listed verified item (`ERR_INCOMPLETE_CLASS_COVERAGE`).

The fee calculation has a pinned evaluation order that resolves an apparent circularity. First the base: the record's class count times 40000 cents per class, stored on `fee_base_cents`. Second the band, read from the base only — never from the total: a base of at least 240000 cents is the `HIGH` band, otherwise `STANDARD`. Third the surcharge: the base times one quarter for `HIGH` or one tenth for `STANDARD`, rounded half-up to whole cents, stored on `fee_surcharge_cents`. Fourth the late fee: the class count times 10000 cents when the filing lands in the grace window, else zero, stored on `late_fee_cents`. Fifth the total, `fee_total_cents`, is the sum of the three components, and `is_late` records whether the grace window applied.

An office decision by a `PartnerAttorney` carries a `decision` of `ACCEPTED` or `REJECTED`. Acceptance — from `SUBMITTED` or `LATE_FILED` — moves the filing to its terminal `ACCEPTED` state and cascades to the record per §3.2: a `MAINTENANCE_DUE` record returns to `REGISTERED`, and in either case all three maintenance horizons advance by ten years. Rejection lands the filing in `REJECTED_OFFICE`, from which a fresh submission re-evaluates the window and may land timely or late. Filings are listed with `trademark_record_id` and `status` filters.

Clearance searches vet candidate marks before adoption. A `ClientContact` (for their own `client_id`) or a `Paralegal` opens a search with the `proposed_mark` and `proposed_classes` (an array of Nice classification integers, each from 1 to 45; the array may be empty), optionally seeding `conflict_hits`; the search starts `OPEN` with `unresolved_hit_count` and `risk_rating` computed. Each hit records a `conflicting_mark`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `IDENTICAL`, and a `disposition` that begins `OPEN`; hits are mutated only through the hit-recording and hit-disposition capabilities. An `AssociateAttorney` appends a hit to an `OPEN` search by `conflicting_mark` and `severity` — a creation returning 201 with the updated search in the body — and disposes a hit by its 0-based `hit_index` — an out-of-range index is `ERR_VALIDATION`, evaluated once the search is known to exist and before its `OPEN` state is checked — setting `disposition` to `WAIVED` or `BLOCKING`. Either mutation recomputes `unresolved_hit_count` (the number of hits still `OPEN`) and `risk_rating`, which is the maximum severity among non-waived hits with `IDENTICAL` mapped to `HIGH`, or `LOW` when nothing non-waived remains. A `PartnerAttorney` finalizes the search: any hit still `OPEN` is rejected with `ERR_UNRESOLVED_HITS`; with none unresolved, the presence of at least one `BLOCKING` hit lands the search in `BLOCKED`, otherwise in `CLEARED`. Both are terminal. Searches are listed with `client_id` and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Escalating a watch alert returns `201 Created` because it creates the enforcement matter, and the response body is the created matter. All endpoints are mounted under `/brand`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/brand/clients` | Create a brand-owner client | PlatformAdmin |
| GET | `/brand/clients/{id}` | Read a client incl. budget and exposure fields | PlatformAdmin, Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/trademark-records` | Register a portfolio mark (ClientContact may only use own client_id) | Paralegal, ClientContact |
| GET | `/brand/trademark-records` | List/filter records | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/trademark-records/{id}` | Read a record | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/trademark-records/{id}/publish` | APPLICATION_PENDING -> PUBLISHED; computes opposition_due_at | Paralegal |
| POST | `/brand/trademark-records/{id}/register` | PUBLISHED -> REGISTERED; computes maintenance windows | Paralegal |
| POST | `/brand/watch-alerts` | Watch-service/manual alert intake; computes provisional score and tier | WatchService, Paralegal |
| GET | `/brand/watch-alerts` | List/filter alerts | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/watch-alerts/{id}` | Read an alert | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/watch-alerts/{id}/triage` | NEW -> TRIAGED | Paralegal |
| POST | `/brand/watch-alerts/{id}/assess` | Record attorney assessment (OCC; supersedes final_score); TRIAGED/MONITORING -> UNDER_ASSESSMENT | AssociateAttorney |
| POST | `/brand/watch-alerts/{id}/escalate` | UNDER_ASSESSMENT -> ESCALATED; creates the EnforcementMatter (response is the matter) | AssociateAttorney |
| POST | `/brand/watch-alerts/{id}/monitor` | UNDER_ASSESSMENT -> MONITORING (40 <= final_score < 70) | AssociateAttorney |
| POST | `/brand/watch-alerts/{id}/dismiss` | UNDER_ASSESSMENT -> DISMISSED (final_score < 40) | AssociateAttorney |
| GET | `/brand/enforcement-matters` | List/filter matters | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/enforcement-matters/{id}` | Read a matter | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/enforcement-matters/{id}/resolve` | ACTIVE -> RESOLVED with outcome; record outcome cascade | PartnerAttorney |
| POST | `/brand/enforcement-matters/{id}/reopen` | RESOLVED -> ACTIVE (manual; breach cascade uses the same transition) | PartnerAttorney |
| POST | `/brand/enforcement-matters/{id}/deadlines` | Docket a deadline on an ACTIVE matter | Paralegal, AssociateAttorney |
| GET | `/brand/deadlines` | List/filter deadlines | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/deadlines/{id}` | Read a deadline | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/deadlines/{id}/verify` | DOCKETED -> PENDING; verifier must differ from docketed_by_user_id | AssociateAttorney, PartnerAttorney |
| POST | `/brand/deadlines/{id}/extend` | PENDING/EXTENDED -> EXTENDED; recomputes computed_due_at | Paralegal |
| POST | `/brand/deadlines/{id}/satisfy` | PENDING/EXTENDED -> SATISFIED (timely); MISSED -> SATISFIED only with allow_late and PartnerAttorney | Paralegal, PartnerAttorney |
| POST | `/brand/enforcement-matters/{id}/cease-desist-letters` | Draft a letter on an ACTIVE matter | AssociateAttorney, PartnerAttorney |
| GET | `/brand/cease-desist-letters` | List/filter letters | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/cease-desist-letters/{id}` | Read a letter | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/cease-desist-letters/{id}/submit-review` | DRAFT -> PENDING_REVIEW | AssociateAttorney, PartnerAttorney |
| POST | `/brand/cease-desist-letters/{id}/approve` | PENDING_REVIEW -> APPROVED (decision APPROVED) or -> DRAFT (decision SENT_BACK); approver != drafter | PartnerAttorney |
| POST | `/brand/cease-desist-letters/{id}/issue` | APPROVED -> ISSUED; accrues issue fee; auto-dockets response deadline | AssociateAttorney |
| POST | `/brand/cease-desist-letters/{id}/record-response` | ISSUED/NEGOTIATING -> COMPLIED / REFUSED / NEGOTIATING by response_outcome | Paralegal |
| POST | `/brand/cease-desist-letters/{id}/reissue` | NEGOTIATING -> ISSUED; accrues reissue fee | AssociateAttorney |
| POST | `/brand/cease-desist-letters/{id}/escalate-litigation` | ISSUED (after response_due_at) or REFUSED -> ESCALATED_LITIGATION | PartnerAttorney |
| POST | `/brand/cease-desist-letters/{id}/void` | DRAFT/PENDING_REVIEW/APPROVED/ISSUED -> VOID; void from ISSUED reverses all accrued letter fees | AssociateAttorney, PartnerAttorney |
| POST | `/brand/watch-alerts/{id}/takedown-filings` | Create a takedown draft against an alert listing | Paralegal |
| GET | `/brand/takedown-filings` | List/filter filings | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/takedown-filings/{id}` | Read a filing | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/takedown-filings/{id}/file` | DRAFT -> FILED; accrues platform fee | Paralegal |
| POST | `/brand/takedown-filings/{id}/platform-response` | FILED/APPEALED -> REMOVED/REJECTED; REMOVED -> REINSTATED; counterfeit counter and referral threshold cascade | Paralegal |
| POST | `/brand/takedown-filings/{id}/appeal` | REJECTED -> APPEALED; cap 2 appeals | Paralegal |
| POST | `/brand/trademark-records/{id}/coexistence-agreements` | Draft a coexistence agreement on a record | AssociateAttorney |
| GET | `/brand/coexistence-agreements` | List/filter agreements | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/coexistence-agreements/{id}` | Read an agreement | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/coexistence-agreements/{id}/propose` | DRAFT/COUNTERED -> PROPOSED (OCC); round cap 8 | AssociateAttorney |
| POST | `/brand/coexistence-agreements/{id}/counter` | PROPOSED -> COUNTERED | AssociateAttorney |
| POST | `/brand/coexistence-agreements/{id}/execute` | PROPOSED/COUNTERED -> EXECUTED; overlap check | PartnerAttorney |
| POST | `/brand/coexistence-agreements/{id}/breach` | MONITORING -> BREACH_ALLEGED; depth-3 cascade (matter reopen -> letter reissue -> auto-docket) | Paralegal |
| POST | `/brand/coexistence-agreements/{id}/cure` | BREACH_ALLEGED -> CURE_PERIOD (GRANT); CURE_PERIOD -> MONITORING (CONFIRM_CURED) | PartnerAttorney |
| POST | `/brand/trademark-records/{id}/evidence-items` | Collect a use specimen for a record | Paralegal, AssociateAttorney |
| GET | `/brand/evidence-items` | List/filter evidence | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/evidence-items/{id}` | Read an evidence item | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/evidence-items/{id}/verify` | COLLECTED -> VERIFIED; verifier != collector | AssociateAttorney, PartnerAttorney |
| POST | `/brand/evidence-items/{id}/reject` | COLLECTED/VERIFIED -> REJECTED | AssociateAttorney, PartnerAttorney |
| POST | `/brand/trademark-records/{id}/maintenance-filings` | Prepare a maintenance/renewal filing | Paralegal |
| GET | `/brand/maintenance-filings` | List/filter filings | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/maintenance-filings/{id}` | Read a filing | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/maintenance-filings/{id}/submit` | PREPARED/REJECTED_OFFICE -> SUBMITTED (in window) or LATE_FILED (grace window) | Paralegal |
| POST | `/brand/maintenance-filings/{id}/office-decision` | SUBMITTED/LATE_FILED -> ACCEPTED (decision ACCEPTED) or REJECTED_OFFICE (decision REJECTED) | PartnerAttorney |
| POST | `/brand/clearance-searches` | Open a clearance search for a candidate mark | ClientContact, Paralegal |
| GET | `/brand/clearance-searches` | List/filter searches | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/clearance-searches/{id}` | Read a search | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/clearance-searches/{id}/conflict-hits` | Append a conflict hit (disposition OPEN) to an OPEN search | AssociateAttorney |
| POST | `/brand/clearance-searches/{id}/dispose-hit` | Set a hit's disposition to WAIVED or BLOCKING by 0-based hit_index | AssociateAttorney |
| POST | `/brand/clearance-searches/{id}/finalize` | OPEN -> CLEARED (no BLOCKING hits) or BLOCKED (any BLOCKING hit); requires no unresolved hits | PartnerAttorney |
| POST | `/brand/trademark-records/{id}/customs-recordations` | Record a mark with a customs authority; buffer-gap rule; optional supersede renewal | Paralegal |
| GET | `/brand/customs-recordations` | List/filter recordations (supersedes_recordation_id filter finds renewals) | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/customs-recordations/{id}` | Read a recordation | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/watch-alerts/{id}/counterfeit-referrals` | Manual referral; requires confirmed counterfeit count of at least 3 | AssociateAttorney |
| GET | `/brand/counterfeit-referrals` | List/filter referrals | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| GET | `/brand/counterfeit-referrals/{id}` | Read a referral | Paralegal, AssociateAttorney, PartnerAttorney, ClientContact |
| POST | `/brand/counterfeit-referrals/{id}/refer` | DRAFT -> REFERRED; CUSTOMS_SEIZE requires an ACTIVE recordation on the record | PartnerAttorney |
| POST | `/brand/counterfeit-referrals/{id}/acknowledge` | REFERRED -> ACKNOWLEDGED | PartnerAttorney |
| POST | `/brand/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC) and run all time-based sweeps | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ENFORCEMENT_BARRED` | 409 |
| `ERR_OPPOSITION_WINDOW_CLOSED` | 422 |
| `ERR_OUTSIDE_FILING_WINDOW` | 422 |
| `ERR_RESPONSE_WINDOW_OPEN` | 422 |
| `ERR_SCORE_BELOW_THRESHOLD` | 422 |
| `ERR_SCORE_ABOVE_DISMISS_CAP` | 422 |
| `ERR_AGREEMENT_OVERLAP` | 409 |
| `ERR_RECORDATION_GAP_VIOLATION` | 409 |
| `ERR_ROUND_CAP_REACHED` | 422 |
| `ERR_APPEAL_CAP_REACHED` | 422 |
| `ERR_EXTENSION_CAP_REACHED` | 422 |
| `ERR_UNRESOLVED_HITS` | 422 |
| `ERR_INCOMPLETE_CLASS_COVERAGE` | 422 |
| `ERR_EVIDENCE_RECORD_MISMATCH` | 422 |
| `ERR_EVIDENCE_NOT_VERIFIED` | 422 |
| `ERR_EVIDENCE_STALE` | 422 |
| `ERR_CLASS_NOT_ON_RECORD` | 422 |
| `ERR_RECORD_NOT_REGISTERED` | 409 |
| `ERR_MATTER_NOT_ACTIVE` | 409 |
| `ERR_PENDING_DEADLINES` | 409 |
| `ERR_REFERRAL_THRESHOLD_NOT_MET` | 422 |
| `ERR_CUSTOMS_RECORDATION_REQUIRED` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
