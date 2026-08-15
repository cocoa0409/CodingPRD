# Architecture Construction Administration API — Product Requirements Document

## 1. Introduction

An architecture firm's construction administration (CA) team shepherds a building contract through its longest and most dispute-prone phase: reviewing submittals and shop drawings against contractual response timeframes, documenting site observation visits in field reports, answering requests for information, certifying payment applications against the schedule of values, advising the owner on change orders, determining substantial and final completion, and billing additional services when the work outlives its contractual duration. Every one of those duties produces dated, attributable evidence, and nearly all of them move either the contract sum or the completion date — figures that owners, contractors, and courts later scrutinize line by line.

This document specifies the Construction Administration API, mounted under `/ca`. The API models the CA phase as a set of peer resources joined by references supplied in request bodies rather than by nested URLs. It tracks the adjusted contract position as change orders incorporate, credits excusable delay when the CA team answers late, derives the firm's extended-duration posture from a server-held logical clock, prices retainage and extended-duration billing under two selectable contractual variants each, and enforces segregation of duties so the person who verifies work is never the person who certifies payment for it. Two writes that legitimately supersede a parent resource's chain tip — clarification drawings and change-order incorporation — are protected by explicit optimistic-concurrency handshakes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles, spelled as follows: `FirmAdmin`, `ArchitectCA`, `Contractor`, and `Owner`. A request that omits either header, presents an empty value, or names a role outside these four is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); the per-endpoint role assignments are enumerated in Section 4.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — there is no user table. The identifier nonetheless carries meaning through comparison and recording, role by role. When `X-User-Role` is `Contractor`, the identifier must equal the acting project's `contractor_user_id` on every project-scoped write; when `X-User-Role` is `Owner`, it must equal the project's `owner_user_id`; a mismatch is rejected with `ERR_NOT_PROJECT_COUNTERPARTY` (HTTP 403). When `X-User-Role` is `ArchitectCA`, the server does not compare the identifier against any project field, but records it where a workflow captures an actor — for example as `certified_by_user_id` at certification time or `recommended_by_user_id` at change-order recommendation — and segregation-of-duties checks compare it against identifiers supplied on earlier calls, such as a visit's `performed_by_user_id` or a report's `issued_by_user_id` (see Section 2.10). When `X-User-Role` is `FirmAdmin`, the identifier is likewise not compared against any entity field and is recorded nowhere; it simply authorizes the firm-administrative operations listed in Section 4.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Every list endpoint returns its resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock, Dates, and Timestamps

All time inside the system reads from a server-held logical clock, never from wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `FirmAdmin` may move it through the clock-setting capability `POST /ca/_clock/set_current_utc`, supplying `to_iso8601` as the new instant; the response reports the resulting `current_utc`, and the operation recomputes the extended-duration posture of every project currently in `ACTIVE` status (the posture rule itself lives in Section 3.8). Every timestamp the server stamps — submissions, reviews, visit performances, report issuances, certifications — reads this clock, and every date comparison in the business rules of Section 3 compares calendar dates derived from it.

Two temporal formats are used throughout. Calendar dates are ISO calendar dates in `YYYY-MM-DD` form; examples include `base_substantial_completion_date`, `visit_date`, `period_ending_date`, `period_start`, and `period_end`. Timestamps are ISO 8601 UTC datetimes rendered with exactly three fractional digits; examples include `received_at`, `performed_at`, `issued_at`, and `certified_at`.

### 2.5. Common Resource Properties

Every resource in the API — projects, submittals, site visits, field reports, RFIs, clarification drawings, payment applications, change orders, punch list items, record documents, and additional-service invoices — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): the same timestamp format, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by one on every mutation, including mutations driven by cascading recomputation described in Section 2.11.

### 2.6. Monetary Precision, Rounding, and Day Counting

All monetary values are integer cents; the API never accepts or emits fractional cents. Wherever a computation produces a fractional cent — a percentage applied to an amount — the product is rounded half up to the nearest cent before it participates in any further arithmetic, and round half up is the only rounding method used. Two pinned rounding orders recur in Section 3 and are worth flagging here: change-order markup rounds each pricing tier to the cent before the tiers are summed, and stored-materials retainage rounds each payment-application line to the cent before the lines are summed. Summing first and rounding once produces a different, non-conformant result in both cases. Day counts such as `credited_delay_days`, `time_extension_days`, `excusable_delay_days`, and `billable_days` are whole integers of calendar dates.

### 2.7. Validation Order and Error Precedence

When several rules could reject the same request, exactly one error is returned: the one from the earliest applicable stage in the following fixed evaluation pipeline.

1. User-context headers — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization against the endpoint's role list — `ERR_FORBIDDEN_ROLE`.
3. Request-body shape: required fields present, types correct, enum values in range, `period_start` strictly before `period_end` where both appear, `lines` non-empty with unique `sov_line_code` values where `lines` appear, and amounts non-negative where declared — `ERR_INVALID_REQUEST`.
4. Resource existence, resolved as described in Section 2.8 — the per-resource not-found errors.
5. Stale-version optimistic-concurrency preconditions — `ERR_STALE_VERSION`.
6. Counterparty ownership for `Contractor`-role and `Owner`-role writes — `ERR_NOT_PROJECT_COUNTERPARTY`.
7. Project lifecycle gates — `ERR_PROJECT_NOT_ACTIVE`, `ERR_PROJECT_NOT_SUBSTANTIAL`, `ERR_PROJECT_NOT_FINAL`, and the closeout aggregate gates detailed in Section 3.7.
8. Target-entity state gates — the family of `ERR_SUBMITTAL_INVALID_STATE`, `ERR_SITE_VISIT_INVALID_STATE`, `ERR_FIELD_REPORT_INVALID_STATE`, `ERR_RFI_INVALID_STATE`, `ERR_PAYMENT_APPLICATION_INVALID_STATE`, `ERR_CHANGE_ORDER_INVALID_STATE`, `ERR_PUNCH_ITEM_INVALID_STATE`, `ERR_RECORD_DOCUMENT_INVALID_STATE`, and `ERR_INVOICE_INVALID_STATE`, together with the chain-tip rule `ERR_LATER_CERTIFIED_APPLICATION_EXISTS`.
9. Segregation-of-duties and conformance gates — `ERR_SOD_REPORT_ISSUER_IS_PERFORMER` and `ERR_SOD_CERTIFIER_IS_VERIFIER` (both HTTP 422), and `ERR_NONCONFORMANCE_NOT_CLEARED` (HTTP 409).
10. Temporal rules — the visit-date conflict, invoice-period overlap, payment-period ordering, the field-report issuance window, and billable-day presence.
11. Referential rules — verification-visit validity, originating-RFI validity, schedule-of-values line membership, clearing-visit validity, and punch-visit validity.
12. Structural constraints — the schedule-of-values sum, the duplicate record-document rule, and the per-line schedule overrun.
13. The fiscal gate on certification — `ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE`.

Consider two illustrations. A certification request whose application is no longer in `SUBMITTED` reports `ERR_PAYMENT_APPLICATION_INVALID_STATE` from stage 8, even if the certifier also performed the verification visit — the state gate precedes the segregation gate. A field-report issuance that violates both segregation of duties and the issuance window reports `ERR_SOD_REPORT_ISSUER_IS_PERFORMER`, because stage 9 precedes stage 10.

### 2.8. Resource Resolution and Not-Found Semantics

Resource identifiers are resolved before any business rule runs. Path identifiers are validated left to right, and the foreign-key identifiers carried in a request body — `project_id`, `site_visit_id`, `rfi_id`, `verification_visit_id`, `raised_visit_id`, `clearing_visit_id` — are validated in the order they appear in the request body. The first identifier that fails to resolve produces the response, and no later check runs. Each resource type has its own not-found error, all HTTP 404: `ERR_PROJECT_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`, `ERR_SITE_VISIT_NOT_FOUND`, `ERR_FIELD_REPORT_NOT_FOUND`, `ERR_RFI_NOT_FOUND`, `ERR_CLARIFICATION_DRAWING_NOT_FOUND`, `ERR_PAYMENT_APPLICATION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_PUNCH_ITEM_NOT_FOUND`, `ERR_RECORD_DOCUMENT_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND`.

### 2.9. Optimistic Concurrency Control

Exactly two writes carry an explicit version handshake, because each legitimately supersedes a parent resource's chain tip.

Issuing a clarification drawing requires the request to carry `expected_rfi_version`, holding the `version` of the parent RFI as the client last observed it. If the RFI's current `version` has advanced since that observation, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). The justification is structural: a new drawing supersedes the previously issued drawing of the same RFI, so a writer holding a stale RFI version would be basing its revision on a superseded chain tip.

Incorporating an owner-accepted change order requires the request to carry `expected_project_version`, matching the project's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because incorporation applies the change order's amount and time extension onto the project's adjusted contract position, and must not run against a financial baseline the client has not observed.

No other endpoint accepts a version field; every other write proceeds without an optimistic-concurrency check.

### 2.10. Segregation of Duties and Counterparty Ownership

Two duties must never collapse onto one person. The CA staff member who issues a field report must differ from the staff member who performed the visit it documents: on issuance, `issued_by_user_id` must differ from the visit's `performed_by_user_id`, or the issuance fails with `ERR_SOD_REPORT_ISSUER_IS_PERFORMER` (HTTP 422). Likewise, the CA staff member who certifies a payment application must differ from the staff member who performed that application's verification visit: the certifier's `X-User-ID` must differ from the verification visit's `performed_by_user_id`, or certification fails with `ERR_SOD_CERTIFIER_IS_VERIFIER` (HTTP 422). Separately, certification is blocked when the verification visit's field report flags nonconforming work that has not been cleared, returning `ERR_NONCONFORMANCE_NOT_CLEARED` (HTTP 409).

Counterparty ownership binds the two external parties to their project records. On any `Contractor`-role write against a project-scoped resource, `X-User-ID` must equal that project's `contractor_user_id`; on any `Owner`-role write, it must equal the project's `owner_user_id`. Violations return `ERR_NOT_PROJECT_COUNTERPARTY` (HTTP 403).

### 2.11. Derived Fields, Recomputation, and Cascading Consistency

Several figures on the project and its children are derived rather than taken from input, and the system recomputes them in full — it never lets them drift incrementally — whenever a source event lands:

- The project's `excusable_delay_days` is the sum of `credited_delay_days` over all of the project's submittals and RFIs, recomputed after every submittal review, submittal vacate, RFI answer, and clarification-drawing issuance.
- The project's `certified_to_date_cents` and `retainage_held_cents` are recomputed from the certified payment chain after every certification, void, and change-order incorporation (Sections 3.5 and 3.6).
- The project's `ca_posture` derives the firm's extended-duration posture from the logical clock and the project's dates (Section 3.8); it is recomputed when the clock is set, when the project activates, whenever excusable delay changes, when a change order incorporates, and when substantial completion is achieved.
- Every additional-service invoice still in `DRAFT` is recomputed whenever the project's excusable delay or adjusted completion date changes, and again when substantial completion is achieved; a draft whose billable days fall to zero cancels itself. Amounts on an invoice that has reached `ISSUED` or beyond are frozen and never recomputed (Section 3.8).

Each such recomputation is a mutation of the affected resource: it refreshes `updated_at` and increments `version`. When one request mutates several resources — a submittal review that shifts the project's excusable delay, posture, and draft invoices all at once, for example — every affected resource is updated as part of that same request.

## 3. Business Logic & Workflows

### 3.1. Project Setup and the Schedule of Values

A `FirmAdmin` opens a construction-administration engagement by creating the project. The creation call carries the project `name`, the opaque counterparty identifiers `owner_user_id` and `contractor_user_id`, the stipulated `original_contract_sum_cents` (which must be positive), and the contractual `base_substantial_completion_date` — the substantial-completion date before any change-order time extensions. Embedded in the same call is the schedule of values, `sov_lines`: an array of entries each pairing a `line_code` with a `description` and a positive `scheduled_value_cents`. Line codes must be unique within the project, and the scheduled values must sum to the original contract sum exactly; a schedule that does not foot to the contract sum is rejected with `ERR_SOV_SUM_MISMATCH` (HTTP 422).

The same creation call also fixes the project's commercial configuration. `daily_extension_rate_cents` and `monthly_extension_rate_cents` (both positive) price the firm's additional services during extended duration, and `billing_method` — either `PER_DIEM_PRORATED` or `WHOLE_MONTH` — selects which rate an invoice uses (Section 3.8). `retainage_mode` — either `TIERED_MARGINAL` or `REDUCTION_AT_HALFWAY` — selects the retainage variant applied to payment applications (Section 3.5). Four optional knobs carry defaults: `grace_days` (at least zero, default 0) defers the start of extension billing past the adjusted completion date; `review_window_days_submittal` (at least one, default 10) sets the calendar days the CA team has to review a submittal; `review_window_days_rfi` (at least one, default 7) sets the calendar days the CA team has to answer an RFI; and `field_report_window_days` (at least one, default 3) sets the calendar days after a performed visit within which its field report must be issued.

A freshly created project initializes its derived position: `adjusted_contract_sum_cents` starts equal to `original_contract_sum_cents`, `adjusted_substantial_completion_date` starts equal to `base_substantial_completion_date`, `excusable_delay_days`, `certified_to_date_cents`, and `retainage_held_cents` all start at zero, `ca_posture` starts at `NORMAL`, `substantial_completion_actual_date` is null, and `status` is `SETUP`. Activation by a `FirmAdmin` moves the project from `SETUP` to `ACTIVE` and recomputes its posture.

The project lifecycle gates nearly everything that follows. Creating a submittal, site visit, RFI, payment application, change order, or punch list item requires the project to be `ACTIVE`; record documents and additional-service invoices may additionally be created while the project is in `SUBSTANTIAL_COMPLETION_ACHIEVED`. Any of these creations attempted against a project in any other state is rejected with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409). The project list endpoint accepts optional `status`, `posture` (matched against `ca_posture`), `owner_user_id`, and `contractor_user_id` filters.

### 3.2. Submittal Review and Excusable-Delay Credit

A `Contractor` submits a submittal or shop-drawing package with the `project_id`, a specification reference `spec_section` (for example "03 30 00"), and the `required_on_site_date` — the calendar date the reviewed package is needed on site. The new submittal lands in `UNDER_REVIEW` with `revision_number` 1, its `received_at` stamped from the logical clock, and its `due_at` computed as `received_at` plus the project's `review_window_days_submittal` calendar days. Its `reviewed_at` and `review_notes` are null and its `credited_delay_days` is zero until the CA team acts. The submittal list endpoint filters by `project_id` and `status`.

Review by an `ArchitectCA` supplies an `outcome` and optional `review_notes`, and four outcomes are possible. `APPROVED` moves the submittal to `APPROVED`; `APPROVED_AS_NOTED` moves it to `APPROVED_AS_NOTED`; both stamp `reviewed_at` from the clock and then run the excusable-delay chain: the submittal's `credited_delay_days` becomes the number of whole calendar days between the date portion of `reviewed_at` and the date portion of `due_at`, or zero when the review lands on or before the due date — a review exactly on the due date credits nothing. (A day here is a whole calendar day of 86,400 seconds; only the date portions of the timestamps are compared.) The project's `excusable_delay_days` is then recomputed as the sum of `credited_delay_days` over all of its submittals and RFIs, its `ca_posture` is rederived, and every `DRAFT` additional-service invoice on the project is recomputed, with any draft whose billable days fall to zero auto-cancelling per Section 3.8. `REVISE_AND_RESUBMIT` and `REJECTED` both stamp `reviewed_at` but set `credited_delay_days` to zero — contractor-caused rework earns no excusable credit — and trigger no project recompute. `REJECTED` is terminal; `REVISE_AND_RESUBMIT` invites a corrected package.

A `Contractor` resubmits a submittal sitting in `REVISE_AND_RESUBMIT`: `revision_number` increments by one, `received_at` is re-stamped from the clock, `due_at` is recomputed from the new `received_at`, `reviewed_at` returns to null, `credited_delay_days` resets to zero, and the submittal is `UNDER_REVIEW` again. An `ArchitectCA` may instead vacate a review, but only from `APPROVED` or `APPROVED_AS_NOTED`: vacating returns the submittal to `UNDER_REVIEW`, subtracts its credited days out of the project's `excusable_delay_days` and resets them to zero, clears `reviewed_at`, re-stamps `received_at`, recomputes `due_at`, and re-runs the posture and draft-invoice recompute chain. Reviewing a submittal that is not `UNDER_REVIEW`, resubmitting one that is not in `REVISE_AND_RESUBMIT`, or vacating one that is not in `APPROVED` or `APPROVED_AS_NOTED` all fail with `ERR_SUBMITTAL_INVALID_STATE` (HTTP 409).

### 3.3. Site Visits, Field Reports, and Nonconforming Work

Site observation begins when an `ArchitectCA` schedules a visit with the `project_id`, a `visit_date`, a `purpose` — one of `PROGRESS_OBSERVATION`, `PAYMENT_VERIFICATION`, `PUNCH_INSPECTION`, or `FINAL_INSPECTION` — and `performed_by_user_id`, the opaque identifier of the CA staff member who will walk the site. A project may host at most one non-cancelled visit per calendar date: if another visit on the same project already holds that `visit_date` in `SCHEDULED`, `PERFORMED`, or `REPORT_ISSUED`, the new schedule is rejected with `ERR_VISIT_DATE_CONFLICT` (HTTP 409). Cancelling a `SCHEDULED` visit moves it to `CANCELLED` and releases its date for reuse. Marking a scheduled visit performed moves it from `SCHEDULED` to `PERFORMED` and stamps `performed_at` from the clock. Performing or cancelling a visit that is not `SCHEDULED` fails with `ERR_SITE_VISIT_INVALID_STATE` (HTTP 409). The visit list filters by `project_id`, `status`, `purpose`, and `performed_by_user_id`.

After a visit is performed, an `ArchitectCA` issues its field report — at most one report per visit — supplying the `site_visit_id`, an `issued_by_user_id`, a `conformance_summary` of `CONFORMING`, `MINOR_DEVIATIONS`, or `NONCONFORMING`, an optional `nonconforming_work_flag` (default false), and optional free-text `notes`. Four checks guard issuance, and they fire in this order: the referenced visit must exist; the visit must be in `PERFORMED` (any other state, including a visit that already has its report, yields `ERR_SITE_VISIT_INVALID_STATE`); segregation of duties requires `issued_by_user_id` to differ from the visit's `performed_by_user_id` (otherwise `ERR_SOD_REPORT_ISSUER_IS_PERFORMER`); and the issuance date read from the clock must be no later than the visit's performed date plus the project's `field_report_window_days` calendar days (otherwise `ERR_FIELD_REPORT_WINDOW_EXPIRED`, HTTP 409). On issuance the report's `issued_at` is stamped and the visit advances from `PERFORMED` to `REPORT_ISSUED` — which is itself what enforces the one-report rule, since a second issuance attempt finds the visit no longer `PERFORMED`.

Every field report carries a derived nonconformance sub-lifecycle. When `nonconforming_work_flag` is false, `nonconformance_status` is `NONE`; when the flag is true, it opens at `OPEN`. An `ArchitectCA` clears an `OPEN` nonconformance by supplying a `clearing_visit_id`. The clearing visit must belong to the same project, be in `REPORT_ISSUED`, have its own field report with `nonconforming_work_flag` false, and have a `performed_at` at or after the flagged visit's `performed_at`; any shortfall is rejected with `ERR_NONCONFORMANCE_CLEARANCE_VISIT_INVALID` (HTTP 422). Clearing against a report whose `nonconformance_status` is not `OPEN` fails with `ERR_FIELD_REPORT_INVALID_STATE` (HTTP 409). A successful clearance records the supplied identifier on the report's `clearing_visit_id` and moves `nonconformance_status` to `CLEARED`, which is effectively terminal for the sub-lifecycle. Field reports list with `site_visit_id`, `issued_by_user_id`, and `clearing_visit_id` filters. The clearance matters downstream: certification of a payment application whose verification visit's report still shows an uncleared nonconformance is blocked, as Section 3.5 describes.

### 3.4. Requests for Information and Clarification Drawings

A `Contractor` files a request for information with the `project_id`, the `question` text, and an optional `cost_impact_flag` (default false) recording whether the contractor anticipates the answer will carry cost impact. The RFI lands `OPEN`, `received_at` is stamped from the clock, and `due_at` is computed as `received_at` plus the project's `review_window_days_rfi` calendar days. Its `answered_at` and `answer_text` stay null and its `credited_delay_days` stays zero until an answer lands. The RFI list filters by `project_id` and `status`.

An `ArchitectCA` answers an `OPEN` RFI with `answer_text` and an optional `requires_clarification_drawing` flag (default false). When the flag is false, the RFI moves directly from `OPEN` to `ANSWERED`: `answered_at` is stamped from the clock, the late-answer credit is computed exactly as for submittals — whole calendar days between the date portion of `answered_at` and the date portion of `due_at`, floored at zero, zero when the answer lands on or before the due date — and stored on the RFI's `credited_delay_days`; then the project's `excusable_delay_days` and `ca_posture` are recomputed and every `DRAFT` invoice on the project recomputes with auto-cancellation at zero billable days. When the flag is true, the RFI instead moves from `OPEN` to `CLARIFICATION_PENDING` with no further effect, awaiting a drawing.

Issuing a clarification drawing is an `ArchitectCA` write carrying the `rfi_id`, a `drawing_ref` such as "SK-12", and the OCC field `expected_rfi_version` described in Section 2.9 — if the RFI's `version` has advanced past what the client observed, issuance is rejected with `ERR_STALE_VERSION` (HTTP 412). The RFI must be in `CLARIFICATION_PENDING` or `ANSWERED`; any other state yields `ERR_RFI_INVALID_STATE`. The first drawing for an RFI takes `revision_number` 1; each subsequent drawing for the same RFI takes one more than the highest existing revision and the previously `ISSUED` drawing is automatically moved to `SUPERSEDED`, so at most one drawing per RFI is ever `ISSUED`. The drawing's `issued_at` is stamped, and the parent RFI's `version` increments by one on every drawing. When the RFI was `CLARIFICATION_PENDING`, the drawing's issuance also moves it to `ANSWERED` — its `answered_at` takes the drawing's clock timestamp, the same late-credit rule applies, and the project's excusable delay, posture, and draft invoices recompute. When the RFI was already `ANSWERED`, no state change occurs; only the supersession and version increment apply. The drawing list filters by `rfi_id` and `status`.

Closure belongs to the contractor. A `Contractor` closes an RFI that is `ANSWERED`, moving it to `CLOSED`, or withdraws one that is still `OPEN`, moving it to `WITHDRAWN`; either call against an RFI in any other state fails with `ERR_RFI_INVALID_STATE`. Both `CLOSED` and `WITHDRAWN` are terminal.

### 3.5. Payment Applications and the Certified Chain

Progress billing starts when a `Contractor` submits a payment application with the `project_id`, the `period_ending_date` closing the billing period, a `verification_visit_id` referencing the payment-verification visit that substantiates the work, and the `lines` — a non-empty array in which each entry names a `sov_line_code` together with `work_completed_this_period_cents` and `stored_materials_cents`, both non-negative, with each schedule-of-values code appearing at most once per application. The application lands in `SUBMITTED` with `revision_number` 1; `rejection_reason`, `certified_at`, `certified_by_user_id`, and `certified_current_due_cents` stay null. The payment-application list filters by `project_id`, `status`, `verification_visit_id`, and `previous_application_id`.

After the global pipeline stages of Section 2.7 (body shape, project existence, counterparty ownership, and the `ACTIVE` lifecycle gate), creation runs its four domain checks in this order. First, period ordering: the new `period_ending_date` must be strictly later than the `period_ending_date` of every other application on the project in `SUBMITTED` or `CERTIFIED` — rejection yields `ERR_PAY_APP_PERIOD_NOT_AFTER_PREVIOUS` (HTTP 409); applications in `REJECTED` or `VOIDED` release their period and no longer block. Second, verification-visit validity: the referenced visit must have `purpose` `PAYMENT_VERIFICATION` and status `REPORT_ISSUED`, and its `visit_date` must fall inside the application's period window — strictly after the previous certified application's `period_ending_date` (for the project's first application there is no lower bound) and on or before this application's own `period_ending_date`; otherwise `ERR_VERIFICATION_VISIT_INVALID` (HTTP 422). Third, every line's `sov_line_code` must exist in the project's `sov_lines`, else `ERR_UNKNOWN_SOV_LINE_CODE` (HTTP 422). Fourth, the per-line schedule cap: for each line, the work previously certified against that same schedule-of-values line across the project's certified applications plus this line's `work_completed_this_period_cents` must not exceed the line's `scheduled_value_cents`, else `ERR_SOV_LINE_OVERRUN` (HTTP 422).

Each application is chained to its predecessor: `previous_application_id` resolves to the `CERTIFIED` application on the same project with the greatest `period_ending_date` strictly before this application's, ties broken by the earlier `created_at`, with `VOIDED` applications excluded from consideration; it is null for the project's first application. Against that chain, the money computation runs in a pinned order — provisionally at creation and resubmission, and again in final form at certification:

1. Identify the previous application per the chain rule. If none exists, the prior cumulative gross is zero; otherwise it is that application's `gross_work_completed_cents`.
2. `earned_work_this_period_cents` is the sum of `work_completed_this_period_cents` over the application's lines.
3. The new cumulative gross, `gross_work_completed_cents`, is the prior cumulative gross plus the earned work this period.
4. The halfway threshold is one half of the project's `adjusted_contract_sum_cents` as it stands at the moment this computation runs, rounded half up to the cent.
5. The retainage held on a gross figure is evaluated under the project's current `retainage_mode`, using the current mode and the current threshold for both the new gross and the prior gross. Under `TIERED_MARGINAL`, the retainage on a gross figure is ten percent of the portion of the gross up to the threshold plus five percent of the portion above it — work at or below the threshold never benefits from the lower rate, so nothing re-bases and there is no cliff. Under `REDUCTION_AT_HALFWAY`, the retainage is ten percent of the entire gross while the gross is below the threshold, and five percent of the entire gross once the gross reaches or exceeds the threshold — the crossing application re-bases all retainage to the lower rate.
6. `retainage_work_cents` is the retainage on the new gross minus the retainage on the prior gross. The difference is negative on the application whose gross crosses the threshold under `REDUCTION_AT_HALFWAY`, which is exactly how a retainage release is expressed.
7. For each line, in lines-array order, the stored-materials retainage is that line's `stored_materials_cents` multiplied by ten percent and rounded half up to the cent; `retainage_stored_cents` is the sum of those per-line figures. Each line is rounded before summing — summing first and rounding once is a different, non-conformant result.
8. The stored-materials total is the sum of `stored_materials_cents` over the lines.
9. The current amount due is the earned work minus `retainage_work_cents`, plus the stored-materials total minus `retainage_stored_cents`.

The provisional variant, run at creation and at resubmission, stores its result in `provisional_current_due_cents` alongside snapshots of `gross_work_completed_cents`, `earned_work_this_period_cents`, `retainage_work_cents`, and `retainage_stored_cents`. The final variant, run at certification time, re-executes the identical formula and stores its result in `certified_current_due_cents`, overwriting the four snapshot fields. The two runs legitimately diverge: a change-order incorporation between creation and certification changes `adjusted_contract_sum_cents` and therefore the halfway threshold (Section 3.6). Every percentage product in the computation is integer cents with round-half-up applied before any subtraction.

Certification by an `ArchitectCA` is gated, and the gates fire in this order: the application must be in `SUBMITTED` (else `ERR_PAYMENT_APPLICATION_INVALID_STATE`); the certifier's `X-User-ID` must differ from the verification visit's `performed_by_user_id` (else `ERR_SOD_CERTIFIER_IS_VERIFIER`, HTTP 422); if the verification visit's field report has `nonconforming_work_flag` true, its `nonconformance_status` must be `CLEARED` (else `ERR_NONCONFORMANCE_NOT_CLEARED`, HTTP 409); and the recomputed `gross_work_completed_cents` must not exceed the project's `adjusted_contract_sum_cents` (else `ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE`, HTTP 402). A successful certification stamps `certified_at` from the clock, records the certifier in `certified_by_user_id`, moves the application to `CERTIFIED`, and recomputes the project's contract position: `certified_to_date_cents` becomes the sum of `certified_current_due_cents` over all of the project's applications in `CERTIFIED` (voided ones excluded), and `retainage_held_cents` becomes the retainage the current mode and current threshold would hold on the `gross_work_completed_cents` of the latest certified application by `period_ending_date`, plus the sum of `retainage_stored_cents` over all certified applications — zero when no certified application exists.

Rejection by an `ArchitectCA` supplies a `reason`, records it in `rejection_reason`, moves the application from `SUBMITTED` to `REJECTED`, and releases its period so the ordering rule no longer counts it. A `Contractor` resubmits a `REJECTED` application with replacement `period_ending_date`, `verification_visit_id`, and `lines`; the replacement values are re-validated exactly as on creation — period ordering, verification-visit validity, line-code membership, and the per-line cap — `revision_number` increments, `rejection_reason` clears to null, and the provisional computation re-runs. Finally, a `FirmAdmin` may void a `CERTIFIED` application, but only from the tip of the certified chain: if any other application on the same project is `CERTIFIED` with a strictly greater `period_ending_date`, the void is rejected with `ERR_LATER_CERTIFIED_APPLICATION_EXISTS` (HTTP 409). A successful void moves the application to `VOIDED`, recomputes the project's `certified_to_date_cents` and `retainage_held_cents` so the certification's contribution is fully compensated, and releases the period for the ordering rule. Certifying, rejecting, resubmitting, or voiding against an application in the wrong state fails with `ERR_PAYMENT_APPLICATION_INVALID_STATE`.

### 3.6. Change Orders and the Adjusted Contract Position

A `Contractor` proposes a change order with the `project_id`, a `title`, and the signed `net_cost_change_cents` — negative for a deduct change, zero for a time-only change. `time_extension_days` (at least zero, default 0) records the calendar days to be added to the completion date on incorporation, and an optional `rfi_id` ties the proposal to an originating RFI. When `rfi_id` is supplied, the referenced RFI must have `cost_impact_flag` true and be in `ANSWERED` or `CLOSED` status; otherwise creation is rejected with `ERR_RFI_NOT_COST_IMPACT` (HTTP 422).

Pricing is computed at creation. The overhead-and-profit `markup_cents` is tiered against the net cost change: ten percent of the first 5,000,000 cents of net change, plus seven percent of the next 5,000,000 cents (the portion between 5,000,000 and 10,000,000), plus four percent of any remainder above 10,000,000 cents. Each tier's product is rounded half up to the cent before the tiers are summed. Deduct and zero-cost changes earn no markup — their `markup_cents` is zero. The change order's `total_amount_cents` is the net cost change plus the markup. The change-order list filters by `project_id`, `status`, and `rfi_id`.

Review proceeds in two stages. An `ArchitectCA` records the firm's recommendation by supplying `recommendation` — `ACCEPT` or `REJECT` — with optional `review_notes`: the change order moves from `SUBMITTED` to `RECOMMEND_ACCEPTANCE` or `RECOMMEND_REJECTION` respectively, and `recommendation` and `recommended_by_user_id` are recorded (both are null until this point). The `Owner` then renders the decision with `decision` — `ACCEPT` or `REJECT` — against a change order in either recommended state: `ACCEPT` moves it to `OWNER_ACCEPTED` and `REJECT` moves it to `OWNER_REJECTED`, and the owner may override the CA recommendation in either direction. Recommending against a change order that is not `SUBMITTED`, or rendering an owner decision against one that is not in `RECOMMEND_ACCEPTANCE` or `RECOMMEND_REJECTION`, fails with `ERR_CHANGE_ORDER_INVALID_STATE` (HTTP 409).

Incorporation is the money move, reserved to the `Owner` and permitted only from `OWNER_ACCEPTED`. The request carries `expected_project_version`, the OCC handshake of Section 2.9: if the project's current `version` differs, incorporation is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the financial baseline from unobserved drift. A successful incorporation moves the change order to `INCORPORATED` and then mutates the project: `adjusted_contract_sum_cents` increases by the change order's `total_amount_cents`, `adjusted_substantial_completion_date` moves out by `time_extension_days` calendar days, and the project's `version` increments by one. The adjusted figures therefore always equal the original contract sum plus the incorporated totals, and the base completion date plus the incorporated extensions. Incorporation then recomputes the project's `ca_posture`, recomputes `retainage_held_cents` under the new adjusted contract sum, and recomputes every `DRAFT` additional-service invoice on the project — auto-cancelling any whose billable days fall to zero.

### 3.7. Completion Determination, Punch List, and Record Documents

Substantial completion is determined by an `ArchitectCA` and requires the project in `ACTIVE` (else `ERR_PROJECT_NOT_ACTIVE`) and at least one site visit on the project with `purpose` `PUNCH_INSPECTION` in `REPORT_ISSUED` status (else `ERR_PUNCH_INSPECTION_REQUIRED`, HTTP 409). On determination the project's `substantial_completion_actual_date` is set to the logical-clock date, the project moves to `SUBSTANTIAL_COMPLETION_ACHIEVED`, its posture is recomputed, and every `DRAFT` additional-service invoice is recomputed with its horizon end fixed to the actual substantial-completion date — auto-cancelling any draft left with zero billable days.

Punch list items are raised by an `ArchitectCA` with the `project_id`, the `raised_visit_id`, a `description` of the deficiency, and its `location`. The referenced visit must be a `PUNCH_INSPECTION` visit in `REPORT_ISSUED` on the same project, else `ERR_PUNCH_VISIT_INVALID` (HTTP 422). A new item opens in `OPEN` with `reopen_count` zero. From `OPEN` or `REOPENED`, a `Contractor` claims completion, moving the item to `CLAIMED_COMPLETE`. An `ArchitectCA` then verifies the claim, moving `CLAIMED_COMPLETE` to `VERIFIED`, or reopens it, supplying a `reason`, moving `CLAIMED_COMPLETE` back to `REOPENED`. A `VERIFIED` item can also be reopened — the machine is deliberately cyclic — but only while the project is `ACTIVE` or `SUBSTANTIAL_COMPLETION_ACHIEVED`; reopening a verified item in any later project state fails with `ERR_PROJECT_NOT_ACTIVE`. Every reopen increments `reopen_count` by one. Claiming from a state other than `OPEN` or `REOPENED`, verifying from a state other than `CLAIMED_COMPLETE`, or reopening from a state other than `CLAIMED_COMPLETE` or `VERIFIED` fails with `ERR_PUNCH_ITEM_INVALID_STATE` (HTTP 409). The punch list filters by `project_id`, `status`, and `raised_visit_id`.

Record documents close out the paperwork. A `Contractor` submits one with the `project_id` and a `doc_type` of `AS_BUILT`, `OM_MANUAL`, `WARRANTY`, or `TEST_REPORT`; it lands in `SUBMITTED` with `revision_number` 1 and null `review_notes`. Only one live document may exist per project and document type: creation is blocked with `ERR_DUPLICATE_RECORD_DOCUMENT` (HTTP 409) while another document of the same project and type sits in `SUBMITTED`, `RETURNED_FOR_CORRECTION`, or `ACCEPTED`. Recall from Section 3.1 that record documents may be created while the project is `ACTIVE` or `SUBSTANTIAL_COMPLETION_ACHIEVED`. An `ArchitectCA` reviews a `SUBMITTED` document with an `outcome` and optional `review_notes`: `ACCEPT` moves it to `ACCEPTED` (terminal), and `RETURN_FOR_CORRECTION` moves it to `RETURNED_FOR_CORRECTION`. A `Contractor` resubmits a returned document, incrementing `revision_number` and returning it to `SUBMITTED`. Reviewing a document not in `SUBMITTED`, or resubmitting one not in `RETURNED_FOR_CORRECTION`, fails with `ERR_RECORD_DOCUMENT_INVALID_STATE` (HTTP 409). The record-document list filters by `project_id`, `status`, and `doc_type`.

Final completion is determined by an `ArchitectCA` and its checks fire in order. The project must be in `SUBSTANTIAL_COMPLETION_ACHIEVED` — an attempt from `ACTIVE` reports `ERR_PROJECT_NOT_SUBSTANTIAL` (HTTP 409). Then the aggregate gates: no punch list item on the project may remain in `OPEN`, `CLAIMED_COMPLETE`, or `REOPENED` (else `ERR_OPEN_PUNCH_ITEMS_REMAIN`), and each of the four document types — `AS_BUILT`, `OM_MANUAL`, `WARRANTY`, and `TEST_REPORT` — must have at least one `ACCEPTED` record document (else `ERR_RECORD_DOCUMENTS_INCOMPLETE`); when both would fail, the punch-item gate is reported first. Success moves the project to `FINAL_COMPLETION_ACHIEVED`.

Closing the project is a `FirmAdmin` act with its own ordered gates. The project must be in `FINAL_COMPLETION_ACHIEVED` (else `ERR_PROJECT_NOT_FINAL`), no payment application may remain in `SUBMITTED` or `REJECTED` (else `ERR_OPEN_PAYMENT_APPLICATIONS`), and no additional-service invoice may remain in `DRAFT`, `ISSUED`, `OWNER_APPROVED`, or `DISPUTED` (else `ERR_OPEN_INVOICES`); open payment applications are reported before open invoices. Success moves the project to `CLOSED`, which is terminal.

### 3.8. Extended-Duration Posture and Additional-Service Billing

When a project runs long, the firm bills the owner for additional services. The gate is the project's derived `ca_posture`: it is `EXTENDED_DURATION` exactly when the project's `status` is `ACTIVE` and the logical-clock date is strictly later than `adjusted_substantial_completion_date` plus `excusable_delay_days` plus `grace_days`; otherwise it is `NORMAL`. The comparison is strict — when the clock date lands exactly on the adjusted date plus delay plus grace, the posture stays `NORMAL`. The derivation re-runs whenever the clock is set, the project activates, excusable delay changes, a change order incorporates, or substantial completion is achieved.

A `FirmAdmin` drafts an invoice with the `project_id`, a `period_start`, and a `period_end`; the start must be strictly before the end or the request fails body-shape validation with `ERR_INVALID_REQUEST`. Periods are exclusive per project: the closed interval from `period_start` through `period_end` must not overlap any other non-cancelled invoice's period on the project, where overlap means the requested start is earlier than the other period's end and the other period's start is earlier than the requested end — two periods sharing a single boundary date are adjacent and allowed. Overlap is rejected with `ERR_INVOICE_PERIOD_OVERLAP` (HTTP 409); cancelling an invoice releases its period for reuse.

The billable content of a draft invoice is computed against a moving horizon. `horizon_start_date` is the project's `adjusted_substantial_completion_date` plus `excusable_delay_days` plus `grace_days`, evaluated at computation time. `horizon_end_date` is the project's `substantial_completion_actual_date` when substantial completion has already been achieved at computation time, and otherwise the logical-clock date at invoice creation. `billable_days` counts the calendar dates that fall within the invoice period, are strictly later than `horizon_start_date`, and are no later than `horizon_end_date`. Creation requires at least one billable day; a period that yields none is rejected with `ERR_NO_BILLABLE_EXTENSION` (HTTP 422). The `amount_cents` then follows the project's `billing_method`: under `PER_DIEM_PRORATED` the amount is `billable_days` times `daily_extension_rate_cents`; under `WHOLE_MONTH` each started thirty-day month bills as a whole month — the billable days are divided by thirty and rounded up to a whole number of months, then multiplied by `monthly_extension_rate_cents`.

Draft invoices track the project's evolving position. On any change to the project's `excusable_delay_days` or `adjusted_substantial_completion_date`, and again when substantial completion is achieved (which fixes the horizon end to `substantial_completion_actual_date`), every invoice of the project still in `DRAFT` recomputes its `horizon_start_date`, `horizon_end_date`, `billable_days`, and `amount_cents`; a draft whose `billable_days` falls to zero automatically transitions to `CANCELLED` and releases its period. Issuance freezes everything: once an invoice leaves `DRAFT`, its `billable_days`, both horizon dates, and `amount_cents` are never recomputed by any subsequent project mutation.

The invoice lifecycle thereafter is administrative. A `FirmAdmin` issues a `DRAFT` invoice, moving it to `ISSUED`. The `Owner` then renders a `decision`: `APPROVE` moves an `ISSUED` invoice to `OWNER_APPROVED`, `DISPUTE` moves it to `DISPUTED`. A `FirmAdmin` records payment of an `OWNER_APPROVED` invoice, moving it to `PAID` (terminal), and may cancel an invoice from `DRAFT` or `DISPUTED`, moving it to `CANCELLED` (terminal) and releasing its period. Issuing or cancelling from a state other than those named, deciding an invoice not in `ISSUED`, or recording payment for one not in `OWNER_APPROVED` fails with `ERR_INVOICE_INVALID_STATE` (HTTP 409). The invoice list filters by `project_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, reviews, certifications, decisions, and the clock set — return `200 OK`. In the role column, "All roles" means all four roles named in Section 2.1. Request bodies, response shapes, and side effects are specified by the workflows of Section 3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ca/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | FirmAdmin |
| POST | `/ca/projects` | Create a CA-phase project with its embedded schedule of values | FirmAdmin |
| GET | `/ca/projects` | List projects with optional filters | All roles |
| GET | `/ca/projects/{id}` | Get one project including all computed financial and posture fields | All roles |
| POST | `/ca/projects/{id}/activate` | Activate a project (SETUP → ACTIVE) | FirmAdmin |
| POST | `/ca/projects/{id}/achieve-substantial-completion` | Determine substantial completion (ACTIVE → SUBSTANTIAL_COMPLETION_ACHIEVED) | ArchitectCA |
| POST | `/ca/projects/{id}/achieve-final-completion` | Determine final completion (SUBSTANTIAL_COMPLETION_ACHIEVED → FINAL_COMPLETION_ACHIEVED) | ArchitectCA |
| POST | `/ca/projects/{id}/close` | Close a project (FINAL_COMPLETION_ACHIEVED → CLOSED) | FirmAdmin |
| POST | `/ca/submittals` | Contractor submits a submittal / shop drawing package | Contractor |
| GET | `/ca/submittals` | List submittals with optional filters | All roles |
| GET | `/ca/submittals/{id}` | Get one submittal | All roles |
| POST | `/ca/submittals/{id}/review` | CA team reviews the current revision (UNDER_REVIEW → outcome state) | ArchitectCA |
| POST | `/ca/submittals/{id}/resubmit` | Contractor resubmits after REVISE_AND_RESUBMIT | Contractor |
| POST | `/ca/submittals/{id}/vacate-review` | CA team vacates an APPROVED / APPROVED_AS_NOTED review, reversing its excusable-delay credit | ArchitectCA |
| POST | `/ca/site-visits` | CA team schedules a site observation visit | ArchitectCA |
| GET | `/ca/site-visits` | List site visits with optional filters | All roles |
| GET | `/ca/site-visits/{id}` | Get one site visit | All roles |
| POST | `/ca/site-visits/{id}/perform` | Mark a scheduled visit performed (SCHEDULED → PERFORMED) | ArchitectCA |
| POST | `/ca/site-visits/{id}/cancel` | Cancel a scheduled visit (SCHEDULED → CANCELLED), releasing its date | ArchitectCA |
| POST | `/ca/field-reports` | Issue the field report for a performed visit (1:1; moves visit to REPORT_ISSUED) | ArchitectCA |
| GET | `/ca/field-reports` | List field reports with optional filters | All roles |
| GET | `/ca/field-reports/{id}` | Get one field report | All roles |
| POST | `/ca/field-reports/{id}/clear-nonconformance` | Clear an OPEN nonconformance using a conforming follow-up visit | ArchitectCA |
| POST | `/ca/rfis` | Contractor files a request for information | Contractor |
| GET | `/ca/rfis` | List RFIs with optional filters | All roles |
| GET | `/ca/rfis/{id}` | Get one RFI | All roles |
| POST | `/ca/rfis/{id}/answer` | CA team answers an RFI directly or marks it as needing a clarification drawing | ArchitectCA |
| POST | `/ca/rfis/{id}/close` | Contractor closes an answered RFI | Contractor |
| POST | `/ca/rfis/{id}/withdraw` | Contractor withdraws an open RFI | Contractor |
| POST | `/ca/clarification-drawings` | Issue a clarification drawing against an RFI (supersedes the previously ISSUED drawing); OCC-guarded on the RFI version | ArchitectCA |
| GET | `/ca/clarification-drawings` | List clarification drawings with optional filters | All roles |
| GET | `/ca/clarification-drawings/{id}` | Get one clarification drawing | All roles |
| POST | `/ca/payment-applications` | Contractor submits a payment application with per-SOV-line work and stored materials | Contractor |
| GET | `/ca/payment-applications` | List payment applications with optional filters | All roles |
| GET | `/ca/payment-applications/{id}` | Get one payment application | All roles |
| POST | `/ca/payment-applications/{id}/certify` | CA team certifies a payment application (SUBMITTED → CERTIFIED) | ArchitectCA |
| POST | `/ca/payment-applications/{id}/reject` | CA team rejects a payment application (SUBMITTED → REJECTED) | ArchitectCA |
| POST | `/ca/payment-applications/{id}/resubmit` | Contractor resubmits a rejected application with replacement period, verification visit, and lines | Contractor |
| POST | `/ca/payment-applications/{id}/void` | Firm admin voids a certified application (CERTIFIED → VOIDED), compensating the certified totals | FirmAdmin |
| POST | `/ca/change-orders` | Contractor submits a change order proposal, optionally originating from a cost-impact RFI | Contractor |
| GET | `/ca/change-orders` | List change orders with optional filters | All roles |
| GET | `/ca/change-orders/{id}` | Get one change order | All roles |
| POST | `/ca/change-orders/{id}/recommend` | CA team records its recommendation to the owner (SUBMITTED → RECOMMEND_*) | ArchitectCA |
| POST | `/ca/change-orders/{id}/owner-decision` | Owner accepts or rejects a recommended change order (may override the recommendation) | Owner |
| POST | `/ca/change-orders/{id}/incorporate` | Owner incorporates an accepted change order into the contract sum and completion date; OCC-guarded on the project version | Owner |
| POST | `/ca/punch-list-items` | CA team raises a punch list item from a punch inspection visit | ArchitectCA |
| GET | `/ca/punch-list-items` | List punch list items with optional filters | All roles |
| GET | `/ca/punch-list-items/{id}` | Get one punch list item | All roles |
| POST | `/ca/punch-list-items/{id}/claim-complete` | Contractor claims a punch item complete (OPEN / REOPENED → CLAIMED_COMPLETE) | Contractor |
| POST | `/ca/punch-list-items/{id}/verify` | CA team verifies completion (CLAIMED_COMPLETE → VERIFIED) | ArchitectCA |
| POST | `/ca/punch-list-items/{id}/reopen` | CA team reopens a claimed or verified item (CLAIMED_COMPLETE / VERIFIED → REOPENED) | ArchitectCA |
| POST | `/ca/record-documents` | Contractor submits a record document (as-built, O&M manual, warranty, test report) | Contractor |
| GET | `/ca/record-documents` | List record documents with optional filters | All roles |
| GET | `/ca/record-documents/{id}` | Get one record document | All roles |
| POST | `/ca/record-documents/{id}/review` | CA team accepts or returns a record document | ArchitectCA |
| POST | `/ca/record-documents/{id}/resubmit` | Contractor resubmits a returned record document | Contractor |
| POST | `/ca/additional-service-invoices` | Firm admin drafts an additional-service invoice for an extended-duration period | FirmAdmin |
| GET | `/ca/additional-service-invoices` | List additional-service invoices with optional filters | All roles |
| GET | `/ca/additional-service-invoices/{id}` | Get one additional-service invoice | All roles |
| POST | `/ca/additional-service-invoices/{id}/issue` | Issue a draft invoice to the owner (DRAFT → ISSUED), freezing its amounts | FirmAdmin |
| POST | `/ca/additional-service-invoices/{id}/owner-decision` | Owner approves or disputes an issued invoice | Owner |
| POST | `/ca/additional-service-invoices/{id}/record-payment` | Firm admin records payment of an approved invoice (OWNER_APPROVED → PAID) | FirmAdmin |
| POST | `/ca/additional-service-invoices/{id}/cancel` | Firm admin cancels a draft or disputed invoice, releasing its period | FirmAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows of Sections 2 and 3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_PROJECT_COUNTERPARTY` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMITTAL_NOT_FOUND` | 404 Not Found |
| `ERR_SITE_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_FIELD_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_RFI_NOT_FOUND` | 404 Not Found |
| `ERR_CLARIFICATION_DRAWING_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PUNCH_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_RECORD_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROJECT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROJECT_NOT_SUBSTANTIAL` | 409 Conflict |
| `ERR_PROJECT_NOT_FINAL` | 409 Conflict |
| `ERR_PUNCH_INSPECTION_REQUIRED` | 409 Conflict |
| `ERR_OPEN_PUNCH_ITEMS_REMAIN` | 409 Conflict |
| `ERR_RECORD_DOCUMENTS_INCOMPLETE` | 409 Conflict |
| `ERR_OPEN_PAYMENT_APPLICATIONS` | 409 Conflict |
| `ERR_OPEN_INVOICES` | 409 Conflict |
| `ERR_SUBMITTAL_INVALID_STATE` | 409 Conflict |
| `ERR_SITE_VISIT_INVALID_STATE` | 409 Conflict |
| `ERR_FIELD_REPORT_INVALID_STATE` | 409 Conflict |
| `ERR_RFI_INVALID_STATE` | 409 Conflict |
| `ERR_PAYMENT_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_LATER_CERTIFIED_APPLICATION_EXISTS` | 409 Conflict |
| `ERR_CHANGE_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_PUNCH_ITEM_INVALID_STATE` | 409 Conflict |
| `ERR_RECORD_DOCUMENT_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_SOD_REPORT_ISSUER_IS_PERFORMER` | 422 Unprocessable Entity |
| `ERR_SOD_CERTIFIER_IS_VERIFIER` | 422 Unprocessable Entity |
| `ERR_NONCONFORMANCE_NOT_CLEARED` | 409 Conflict |
| `ERR_VISIT_DATE_CONFLICT` | 409 Conflict |
| `ERR_INVOICE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_PAY_APP_PERIOD_NOT_AFTER_PREVIOUS` | 409 Conflict |
| `ERR_FIELD_REPORT_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_NO_BILLABLE_EXTENSION` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_VISIT_INVALID` | 422 Unprocessable Entity |
| `ERR_RFI_NOT_COST_IMPACT` | 422 Unprocessable Entity |
| `ERR_UNKNOWN_SOV_LINE_CODE` | 422 Unprocessable Entity |
| `ERR_NONCONFORMANCE_CLEARANCE_VISIT_INVALID` | 422 Unprocessable Entity |
| `ERR_PUNCH_VISIT_INVALID` | 422 Unprocessable Entity |
| `ERR_SOV_SUM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RECORD_DOCUMENT` | 409 Conflict |
| `ERR_SOV_LINE_OVERRUN` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE` | 402 Payment Required |
