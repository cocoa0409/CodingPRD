# Escheatment & Unclaimed Property API — Product Requirements Document

## 1. Introduction

Financial institutions — banks, brokerages, insurers, and check issuers — routinely hold property whose owners have gone silent: dormant checking and savings balances, uncashed checks, unpaid insurance proceeds, and share positions with accrued dividends. Every U.S. state obliges the holder of such property to track owner inactivity against statutory dormancy periods, to attempt due-diligence outreach before reporting, to file an annual holder report and remit the property's value to the state, and to expose itself to penalties, interest, and audit when it files late. Once the state holds custody, the owner's path back to the property runs through a formal claim and reunification process.

This document specifies the Escheatment & Unclaimed Property API, the system of record through which a holder administers that entire statutory pipeline. All endpoints are mounted under `/escheatment`. The API covers dormancy-rule configuration and the dormancy sweep, due-diligence letter timing and response tracking, holder report preparation and amendment, securities liquidation, remittance and the transfer of custody, owner claims and payout, late-filing penalty and interest exposure, state audit defense, and evidence retention. Because every obligation in this domain is dated by statute, the server runs on a controllable logical clock rather than wall-clock time, and a single sweep operation applies time-based transitions on demand.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. If either header is missing, or the role supplied is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Access to each operation is restricted by role per the endpoint table in §4; a caller whose role is not permitted on an endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes eight roles. `HolderAdmin` is the holder's unclaimed-property system administrator, responsible for dormancy configuration, the logical clock, sweeps, and retention purges. `ComplianceOfficer` is the holder's compliance officer, responsible for owners, properties, contacts, due-diligence letters, report preparation, submission and amendment, document registration, and penalty disputes. `StateAuditor` is the state's unclaimed-property administrator, who accepts or rejects reports, confirms or fails remittances, takes custody of property, assesses, waives and upholds penalties, and runs audits. `TreasuryOps` is the holder's treasury operations desk, responsible for securities liquidation, remittance preparation and requeue, penalty payment, and claim payout disbursement. `ClaimsExaminer` opens claim review and requests information but is forbidden from approving or denying, under segregation of duties. `ClaimsApprover` holds claim decision authority and must never be the reviewing examiner on the same claim. `Claimant` is a property owner filing for reunification, scoped strictly to their own resources. `Any` is a pseudo-role standing for any authenticated principal and is used on the read-only retrieval endpoints, where `X-User-Role` may carry any declared role.

Two forms of identity binding apply. When `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks on any resource that references an `Owner` compare the resource's owner-linkage field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_SCOPE_VIOLATION` (HTTP 403). When `X-User-Role` is any of `HolderAdmin`, `ComplianceOfficer`, `StateAuditor`, `TreasuryOps`, `ClaimsExaminer`, `ClaimsApprover`, or the pseudo-role `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `recorded_by_user_id` on a contact event, `submitted_by_user_id` on a report, or `reviewed_by_user_id` and `decided_by_user_id` on a claim — but never compares it to any entity's `id`.

Segregation of duties is enforced wherever one officer's work must be checked by another: the operator who accepts a submitted report must not be the operator recorded as its `submitted_by_user_id`, and the approver or denier of a claim must not be the examiner recorded as its `reviewed_by_user_id`. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource exposed by this API — owners, dormancy rules, properties, contact events, due-diligence letters, holder reports, report line items, securities details, liquidation orders, remittances, owner claims, penalty assessments, audit cases, and document records — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a bare UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments with every modification to the resource, including modifications driven by cascades and recomputations rather than by a direct client write.

This convention provides a consistent audit trail and unique addressability for every entity in the system.

### 2.5. The Logical Clock and Statutory Calendar Semantics

Escheatment obligations are dated by statute, so the server keeps its own **logical clock** and never consults wall-clock time. Before any explicit adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `HolderAdmin` may move the clock to a supplied `to_iso8601` instant; the response reports the new reading as `current_utc`. Setting the clock fires no state transitions by itself — time-based rules take effect only when the dormancy sweep described in §3.2 is run against the current logical reading.

Every phrase in this document of the form "the clock date" or "the clock datetime" — the stamps recorded into `sent_date`, `submitted_date`, `accepted_date`, `confirmed_date`, `executed_date`, `settled_date`, `paid_date`, `assessed_date`, `escheated_date`, `reunited_date`, and `purged_at` — refers to this logical clock. Calendar-date fields are ISO dates of the form `YYYY-MM-DD`, and all date arithmetic is performed in whole days. Two interval conventions recur throughout: dormancy-rule effective windows are half-open, treating their start date as inclusive and their end date as exclusive, while audit lookback windows are closed intervals that include both endpoint years. An anniversary calculation — for example adding a rule's dormancy years to a contact date — lands on the same month and day the stated number of years later; where such a derivation would land on February 29 of a year that has none, the result clamps to February 28.

### 2.6. Monetary Representation, Basis Points, and Rounding Discipline

All monetary amounts in this API are represented as integer numbers of cents; no field ever carries a fractional cent. Rates are expressed in basis points, so a configured `annual_interest_rate_bp` of 1200 means twelve percent per annum, and the claim processing fee of 150 basis points means one and a half percent. Wherever a daily interest accrual is prescribed, the divisor is exactly 3,650,000 — ten thousand basis points multiplied by a 365-day year — so that a whole year's accrual at a configured rate yields precisely that rate on the base.

Rounding follows three fixed conventions, stated again where each applies. "Round half up" rounds a fractional result to the nearest whole cent, with exact halves rounding up. "Floor" rounding, used for penalty caps, rounds down to a whole cent. Where interest is computed per report line, each line's interest is rounded half-up to whole cents first and the rounded amounts are then summed; summing the unrounded amounts and rounding once at the end is a different procedure and can diverge from the prescribed result by a cent or more. Securities valuation arithmetic involves only integer inputs and requires no rounding at all.

### 2.7. Optimistic Concurrency Control on Reports

Two write operations — adding a line item to a holder report, and creating an amendment that supersedes an accepted report — require the request body to carry `expected_report_version`, holding the `version` of the report as the client last observed it. If the report's current `version` has advanced beyond that observed value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). For line-item addition, the check prevents a client from admitting another line on the basis of report totals computed from a stale read; for amendment creation, it ensures the client's view of the amendment chain head is current, since an amendment legitimately supersedes the prior head. A mismatch forces a re-read before the write can proceed. No other endpoint in the API accepts a version field.

### 2.8. Cascading State Propagation and Eager Recomputation

This system maintains hierarchical consistency automatically: when an operation's effects cross entity boundaries, the server applies every hop of the cascade itself, without requiring separate client calls on the affected resources. A property's reactivation removes its lines from draft reports; a report's acceptance advances its properties' pipeline states and supersedes the report it amends; a liquidation settlement finalizes a report line and refreshes a pending remittance's variance; a remittance confirmation moves properties into state custody readiness; a claim payout reunites the property with its owner. A holder report's derived totals — `total_provisional_cents`, `total_final_cents`, and `line_count` — are never written by clients; they are recomputed eagerly on every mutation that touches the line set. Every such secondary mutation refreshes the affected resource's `updated_at` and increments its `version`, so observers can detect cascade-driven change exactly as they detect direct writes. The individual cascades are specified hop by hop in §3 alongside the workflows that trigger them.

### 2.9. Nested Resource Retrieval

The API enforces strict, hierarchical validation for all requests whose paths contain multiple resource identifiers. Identifiers are validated in sequential, left-to-right order, and the request is rejected immediately with the not-found error corresponding to the first identifier that does not exist: `ERR_OWNER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_DORMANCY_RULE_NOT_FOUND`, `ERR_CONTACT_EVENT_NOT_FOUND`, `ERR_LETTER_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_SECURITIES_DETAIL_NOT_FOUND`, `ERR_LIQUIDATION_ORDER_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PENALTY_ASSESSMENT_NOT_FOUND`, `ERR_AUDIT_CASE_NOT_FOUND`, or `ERR_DOCUMENT_RECORD_NOT_FOUND` (each HTTP 404). A request targeting a line item under a report that does not exist therefore fails with `ERR_REPORT_NOT_FOUND` before the line is ever examined, and a line item that exists but does not belong to the report named in the path is likewise reported as `ERR_LINE_ITEM_NOT_FOUND`.

### 2.10. Layered Validation Order

Every request is validated in a fixed sequence of layers, and a failure in an earlier layer masks all later checks — the caller always receives the earliest applicable error. The layers, in order, are: first, the presence and validity of the authentication headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role authorization on the endpoint (`ERR_UNAUTHORIZED_ROLE`); third, request-body well-formedness — required fields present, types matching, enum values in range, date strings parseable, integers inside their declared ranges — with any violation rejected as `ERR_INVALID_REQUEST` (HTTP 400); fourth, left-to-right path existence per §2.9; fifth, claimant ownership scoping (`ERR_OWNERSHIP_SCOPE_VIOLATION`); sixth, segregation of duties (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`); seventh, the optimistic concurrency check of §2.7 (`ERR_STALE_VERSION`); eighth, the target resource's own state-machine precondition for the attempted transition (the state-error family, HTTP 409); ninth, uniqueness and overlap constraints such as one active letter per property or one report per period (HTTP 409); tenth, temporal windows — the due-diligence send window, the liquidation execution grace, the document retention gate (HTTP 409); eleventh, the state and configuration of referenced entities, such as rule applicability, state-code agreement, and evidence qualification (HTTP 422, with `ERR_PROPERTY_IN_SUBMITTED_REPORT` at HTTP 409); and twelfth, amount-level fiscal checks such as zero remittance variance (HTTP 422). Where an endpoint carries several checks inside one layer, §3 states their relative order alongside the workflow; and where a §3 workflow enumerates an endpoint's checks in an explicit order, that stated order governs over the default layer numbering above — so, for example, the state check on report acceptance and on claim approval or denial precedes the segregation-of-duties check, the property-type check on securities-detail registration precedes the one-to-one uniqueness check, and a liquidation request's property checks precede its duplicate-order check.

## 3. Business Logic & Workflows

### 3.1. Registering Owners and Their Property

Every escheatment case begins with a registered **owner**. A `ComplianceOfficer` registers an owner by supplying the `full_name`, the `last_known_address` as a free-form single line, and the `state_code` — the two-letter state of the last known address, which fixes the escheatment jurisdiction that will govern everything the owner later leaves behind. An optional `deceased_date`, an ISO calendar date, may be recorded to support later estate claims; when omitted it remains null. The owners listing may be filtered by `state_code`, and owner records are broadly readable — with the claimant-scoping carve-out described at the end of this subsection.

With an owner on file, a `ComplianceOfficer` registers each item of property through a payload containing the `owner_id`, the `property_type`, the governing `state_code`, the declared `original_value_cents`, and the `last_contact_date`. The property type is one of `CHECKING`, `SAVINGS`, `BROKERAGE_SHARES`, `UNCASHED_CHECK`, or `INSURANCE_PROCEEDS`. Registration enforces two guards. The property's `state_code` must equal the owning owner's `state_code`; a mismatch is rejected with `ERR_OWNER_STATE_MISMATCH`. And an applicable dormancy rule — one covering the property's state and type, effective at the `last_contact_date` per the applicability test of §3.2 — must exist; without one, registration fails with `ERR_NO_APPLICABLE_DORMANCY_RULE`. The declared value must be an integer greater than zero. For `BROKERAGE_SHARES` it carries the estimated market value and serves only for due-diligence thresholding; it is never treated as a valuation of the shares themselves.

A new property starts `ACTIVE`, with `dormancy_date`, `escheated_date`, and `reunited_date` all null. From there its `status` walks the statutory pipeline — `ACTIVE`, `DORMANT`, `DUE_DILIGENCE`, `REPORTABLE`, `REPORTED`, `REMITTED`, `ESCHEATED` — and may leave it at the end for `REUNITED`, the terminal state, when a paid claim returns the property to its owner. The transitions are driven by the workflows of §3.2 through §3.7, never by direct status writes.

**Contact events** are the raw evidence of owner activity. A `ComplianceOfficer` records a contact against a property with a payload carrying the `contact_type`, the `contact_date` — which may be backdated — and an `evidence_ref`, a document or statement reference required for every contact type. The recognized contact types are `WITHDRAWAL`, `DEPOSIT`, `LOGIN_VERIFIED`, `WRITTEN_CORRESPONDENCE`, `PHONE_VERIFIED`, and `IN_PERSON`. From the type, the server derives `qualifies_for_reactivation`: it is true for `WITHDRAWAL`, `DEPOSIT`, `WRITTEN_CORRESPONDENCE`, and `IN_PERSON`, and always false for `LOGIN_VERIFIED` and `PHONE_VERIFIED`, which are considered too weak to prove the owner is alive and engaged. The recorder's `X-User-ID` is captured as `recorded_by_user_id`. Every recorded contact also refreshes the property it concerns: the `last_contact_date` advances to the later of its current value and the event's `contact_date`, and it is this maintained date that the dormancy sweep of §3.2 measures against.

A `Claimant` may record contact events too, but only against a property whose owner is the claimant; acting outside that ownership scope is refused with `ERR_OWNERSHIP_SCOPE_VIOLATION`. The same scoping governs claimant reads: any authenticated principal may list properties — filtering by `owner_id`, `state_code`, or `status` — list one owner's properties, list the claims filed by an owner, and list a property's contact events, report line items, and claims, but when the caller is a `Claimant`, single-resource reads of an owner, a property, or a claim succeed only where the record's owner linkage equals the caller's `X-User-ID`, and otherwise fail with `ERR_OWNERSHIP_SCOPE_VIOLATION`. A `Claimant` listing one specific owner's properties or one specific owner's claims is scoped the same way — naming another owner's id in the path fails with `ERR_OWNERSHIP_SCOPE_VIOLATION` — while the per-property listings (contact events, report line items, claims) apply no claimant scoping.

### 3.2. Dormancy Rules and the Dormancy Sweep

Dormancy policy is configuration, not code. A `HolderAdmin` authors a **dormancy rule** for a pairing of `state_code` and `property_type`, setting `dormancy_years` — the years of owner silence, an integer from 1 to 15 inclusive, after which property is presumed abandoned — together with an effective window delimited by `effective_from` and an optional `effective_to`. The window is half-open: the rule governs contact dates on or after `effective_from` and strictly before `effective_to`, and a null `effective_to` leaves the rule open-ended. Two rules for the same state and property type may not have overlapping windows; the attempt is rejected with `ERR_DORMANCY_RULE_OVERLAP`. Adjacency is expressly permitted — an existing rule whose `effective_to` equals the new rule's `effective_from` hands off cleanly and is not an overlap. The same overlap check runs again whenever a `HolderAdmin` updates a rule: an update may revise any subset of `dormancy_years`, `effective_from`, `effective_to`, and the ten configurable thresholds and calendar fields, re-validates the effective window against sibling rules, and increments the rule's `version`. The `state_code`/`property_type` pairing itself is immutable — values supplied for either in an update are ignored. The rules listing may be filtered by `state_code` and `property_type`.

Every rule also carries the statutory knobs the rest of the pipeline consults, each taking a default when the author omits it. The due-diligence threshold `dd_threshold_cents` defaults to 5000 — fifty dollars — and decides both whether a letter is required before reporting and how the sweep treats a dormant property. The letter send window is bounded by `dd_window_min_days` and `dd_window_max_days`, defaulting to 60 and 180: a letter may go out no later than sixty days before the report due date and no earlier than one hundred eighty days before it. The late-filing penalty schedule defaults to a `daily_penalty_cents` of 10000, one hundred dollars per day, escalating to a `gross_daily_penalty_cents` of 25000 once lateness runs strictly beyond the `gross_negligence_day_threshold` of 30 days, with the whole penalty capped at `penalty_cap_pct` — 25 percent by default — of the report's provisional total. Late remittance and claim interest accrue at `annual_interest_rate_bp` basis points per annum, defaulting to 1200, or twelve percent. The reporting calendar defaults to a `report_cutoff_month_day` of `06-30` and a `report_due_month_day` of `11-01`: property dormant on or before the cutoff enters that year's report cycle, and the report falls due on the due date. Every numeric knob must be an integer of zero or more, and each calendar field must be an `MM-DD` string naming a valid month and day; violations are `ERR_INVALID_REQUEST`.

Which rule applies to a given property is determined by an exact match on `state_code` and `property_type` whose effective window contains the property's `last_contact_date` — `effective_from` on or before that date, and `effective_to` either null or strictly after it. Registration treats a missing rule as an error, per §3.1. The sweep treats it as a skip: a property with no applicable rule is simply passed over, without error.

A `HolderAdmin` runs the dormancy sweep against the current logical clock, and the sweep applies time's consequences in three passes. The first pass examines every `ACTIVE` property that has an applicable rule: it computes the anniversary of the `last_contact_date` after adding the rule's `dormancy_years` — the same month and day, that many years later — and when the sweep date is strictly later than that anniversary, the property transitions `ACTIVE → DORMANT` and its `dormancy_date` is set to the day immediately following the anniversary. A sweep running exactly on the anniversary changes nothing; the property remains `ACTIVE`. The second pass considers only properties that were already `DORMANT` when the sweep started: any of them whose `original_value_cents` falls below the applicable rule's `dd_threshold_cents` — due diligence not required — advances `DORMANT → REPORTABLE` at once (a `DORMANT` property with no applicable rule is again skipped, without error). A property therefore advances at most one dormancy step per invocation; one that turned `DORMANT` in the first pass is not reconsidered for reportability until a later sweep. The third pass expires letters: any due-diligence letter still `SENT` or `DELIVERED` whose `response_deadline` is strictly before the sweep date becomes `EXPIRED` — on the deadline day itself the letter remains open — and its property falls from `DUE_DILIGENCE` to `REPORTABLE`. The sweep response enumerates what it touched, as `transitioned_property_ids`, `expired_letter_ids`, and `reportable_property_ids`.

Two report-calendar derivations serve both letter targeting here and audit exposure in §3.8. For any year, the cycle's cutoff date combines that year with the rule's `report_cutoff_month_day`, and its due date combines the year with `report_due_month_day`. The first eligible cycle for a dormant property is the earliest year whose cutoff date falls on or after the property's `dormancy_date`. If that cycle's due date is already in the past relative to the current logical date, the cycle rolls forward one year at a time until the due date is no longer in the past — on or after the current date — and that cycle's due date becomes the `applicable_due_date`. A due-diligence letter's permitted send window then opens `dd_window_max_days` before the applicable due date and closes `dd_window_min_days` before it, both boundary days inclusive.

### 3.3. Due-Diligence Outreach and Reactivation

Before an over-threshold property may be reported, the holder must attempt to reach its owner in writing. A `ComplianceOfficer` sends a due-diligence letter against a dormant property; the request itself carries no body, because everything about the letter derives from the rule and the logical clock. Five checks guard creation, evaluated in a fixed order — state first, then uniqueness, then applicable-rule existence, then the send window, then the threshold — so that, for example, a letter attempt on an `ACTIVE` property surfaces `ERR_PROPERTY_NOT_DORMANT` rather than being masked by a later check. The property must be `DORMANT` or `DUE_DILIGENCE`, else `ERR_PROPERTY_NOT_DORMANT`; `DUE_DILIGENCE` is admitted deliberately so that a second letter attempt reaches the duplicate check, since a property in that state always has an active letter on file. No other letter for the property may be `SENT` or `DELIVERED`, else `ERR_DUPLICATE_ACTIVE_LETTER`. An applicable dormancy rule per §3.2 must still cover the property, else `ERR_NO_APPLICABLE_DORMANCY_RULE`. The send date — the logical clock date — must fall inside the inclusive window from `dd_window_max_days` before the `applicable_due_date` through `dd_window_min_days` before it, else `ERR_DUE_DILIGENCE_WINDOW_VIOLATION`. And the property's `original_value_cents` must be at or above the rule's `dd_threshold_cents`; below it, due diligence is not required and creation is refused with `ERR_DUE_DILIGENCE_NOT_REQUIRED`. On success the property itself advances `DORMANT → DUE_DILIGENCE`.

A created letter starts `SENT`, stamped with a `sent_date` equal to the clock date, a `response_deadline` exactly thirty days after the `sent_date`, the `applicable_due_date` derived per §3.2, the `property_id` of its property, and `response_contact_event_id` null. From there the letter's `status` walks a small machine whose terminal states are `RESPONDED`, `EXPIRED`, `UNDELIVERABLE`, and `VOIDED`. A `ComplianceOfficer` may mark a `SENT` letter delivered, moving it `SENT → DELIVERED`; may mark a letter undeliverable from either `SENT` or `DELIVERED`, moving it to `UNDELIVERABLE` and dropping its property `DUE_DILIGENCE → REPORTABLE`; and may record an owner's response from either `SENT` or `DELIVERED`, as described next. Any of these actions attempted on a letter not in an acceptable state is refused with `ERR_LETTER_NOT_ACTIONABLE`. Expiry belongs to the sweep: a letter still `SENT` or `DELIVERED` whose deadline has strictly passed becomes `EXPIRED` and its property likewise becomes `REPORTABLE`, as §3.2 describes.

Recording a response takes a payload naming the `response_contact_event_id` of the contact event that evidences the owner's reply. The letter's own state check above runs first; only then is the evidence examined. That event must exist (otherwise `ERR_CONTACT_EVENT_NOT_FOUND`), must belong to the same property (otherwise `ERR_CONTACT_EVENT_PROPERTY_MISMATCH`), must be one whose `qualifies_for_reactivation` is true, and must carry a `contact_date` on or after the letter's `sent_date` — a qualifying-type or date failure surfaces as `ERR_CONTACT_NOT_QUALIFYING`. On success the letter becomes `RESPONDED` with `response_contact_event_id` recorded, and the property returns `DUE_DILIGENCE → ACTIVE` with the full reactivation cascade below: the property's `last_contact_date` advances to the later of its current value and the evidence event's `contact_date`.

Reactivation proper is the broader door back to good standing. A `ComplianceOfficer` reactivates a property by citing an `evidence_contact_event_id`. The property must be `DORMANT`, `DUE_DILIGENCE`, or `REPORTABLE`, else `ERR_PROPERTY_NOT_REACTIVATABLE`; the cited event must exist, belong to this property, and qualify, under the same three evidence errors as above. When the property is `REPORTABLE`, one more guard applies: no line in `INCLUDED` or `FINAL` status for this property may belong to a report that is `SUBMITTED` or `ACCEPTED` — a property already bound into a filed report cannot be pulled back, and the attempt is refused with `ERR_PROPERTY_IN_SUBMITTED_REPORT`. Reactivation's effects ripple outward in hops. The property returns to `ACTIVE`, its `last_contact_date` advances to the later of its current value and the evidence's `contact_date`, and its `dormancy_date` is cleared back to null. Any letter for the property still `SENT` or `DELIVERED` is voided to `VOIDED`. Every report line item for this property with status `INCLUDED` whose containing report is still `DRAFT` is removed to `REMOVED`. And each affected draft report recomputes its `total_provisional_cents`, `total_final_cents`, and `line_count`, with its `version` incrementing — the same eager recomputation §2.8 prescribes, and the reason a stale `expected_report_version` on a subsequent line addition will correctly fail.

### 3.4. Assembling, Submitting, and Amending Holder Reports

The annual **holder report** is the instrument that hands property to the state. A `ComplianceOfficer` opens one for a destination `state_code` and a `report_year`; only one report per state-and-year pair may exist outside `SUPERSEDED`, and a duplicate base report is refused with `ERR_DUPLICATE_REPORT_PERIOD` — amendments, which carry a `supersedes_report_id`, are expressly exempt from this rule. The report is created in `DRAFT`, with its `cutoff_date` and `due_date` derived from the state's dormancy-rule configuration — the first rule configured for that state supplies the calendar fields, and when no rule for the state exists yet the defaults `06-30` and `11-01` supply them, so report creation is never blocked by missing rule configuration — by combining the `report_year` (a positive integer) with `report_cutoff_month_day` and `report_due_month_day` respectively; `submitted_date`, `submitted_by_user_id`, `accepted_date`, and `rejection_reason` begin null, and the computed totals `total_provisional_cents`, `total_final_cents`, `confirmed_remittance_cents`, and `line_count` begin at zero. The reports listing may be filtered by `state_code`, `report_year`, or `status`; a non-integer `report_year` filter is rejected with `ERR_INVALID_REQUEST`.

Into a `DRAFT` report, a `ComplianceOfficer` adds line items, one property per line, through a payload containing the `property_id` and the `expected_report_version` required by §2.7 — a mismatch with the report's current `version` is rejected with `ERR_STALE_VERSION` before anything else about the line is considered — only the path identifiers and the existence of the body-referenced property (a `property_id` naming no existing property fails with `ERR_PROPERTY_NOT_FOUND`) are resolved ahead of the version check. The report must be `DRAFT`, else `ERR_REPORT_NOT_DRAFT`. The property must be `REPORTABLE` and of the report's own state, else `ERR_PROPERTY_NOT_REPORTABLE`; and a `BROKERAGE_SHARES` property must already carry its securities detail, else `ERR_SECURITIES_DETAIL_REQUIRED`. The new line starts `INCLUDED`, records the containing report's `report_id`, and derives its `line_type` — `SECURITIES` when the property is `BROKERAGE_SHARES`, otherwise `CASH` — and its `provisional_value_cents`: for `CASH`, simply the property's `original_value_cents`; for `SECURITIES`, the provisional securities valuation of §3.5 at inclusion time. The line's `final_value_cents` stays null until finalization. Removing a line is permitted only while the report is `DRAFT` (else `ERR_REPORT_NOT_DRAFT`) and the line is `INCLUDED` (else `ERR_LINE_ITEM_NOT_REMOVABLE`); removal moves the line to `REMOVED`, its terminal state along with `FINAL`.

A report's totals are never written by hand. At every line addition, line removal, submission, liquidation settlement, amendment copy, and reactivation cascade, the included set — lines in `INCLUDED` or `FINAL`, excluding `REMOVED` — is re-aggregated: `total_provisional_cents` is the sum of the included lines' `provisional_value_cents`; `total_final_cents` sums, for each included line, its `final_value_cents` when the line is `FINAL` and its `provisional_value_cents` otherwise; and `line_count` is the size of the included set. Each recomputation refreshes the report's `updated_at` and increments its `version`.

Submission is the point of no return for cash values. A `ComplianceOfficer` submits a report that is `DRAFT` (else `ERR_REPORT_NOT_DRAFT`), holds at least one line in `INCLUDED` or `FINAL` status (else `ERR_EMPTY_REPORT`) — so a reopened report whose cash lines already finalized remains resubmittable — and has completed due diligence: for every `INCLUDED` line whose property's `original_value_cents` is at or above the applicable rule's `dd_threshold_cents` (a line whose property no longer has an applicable rule at submission time is treated as over-threshold), that property must show at least one letter in a terminal state — `EXPIRED` or `UNDELIVERABLE` — else the submission is refused with `ERR_DUE_DILIGENCE_INCOMPLETE`. On submission the report's `submitted_date` is set to the clock date, `submitted_by_user_id` records the submitting officer, and every `INCLUDED` line of `line_type` `CASH` finalizes — moving `INCLUDED → FINAL` with its `final_value_cents` set equal to its `provisional_value_cents` — while `SECURITIES` lines remain `INCLUDED` pending liquidation. The report becomes `SUBMITTED` and its `version` increments.

The state then rules on the filing. A `StateAuditor` accepts a report that is `SUBMITTED` (else `ERR_REPORT_NOT_SUBMITTED`), and the acceptor's identity must differ from the recorded `submitted_by_user_id` — an officer may never accept their own submission, and the attempt is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Acceptance stamps `accepted_date` with the clock date, increments the report's `version`, and cascades: every property with an `INCLUDED` or `FINAL` line in the report advances `REPORTABLE → REPORTED`, and when the accepted report is an amendment — its `supersedes_report_id` set — the superseded report moves `ACCEPTED → SUPERSEDED`, the only terminal state a report has. A `StateAuditor` may instead reject a `SUBMITTED` report — any other state is likewise refused with `ERR_REPORT_NOT_SUBMITTED` — recording the supplied `rejection_reason`. A `ComplianceOfficer` may then reopen a `REJECTED` report — reopening any other state is refused with `ERR_REPORT_NOT_REJECTED` — returning it to `DRAFT` and clearing `submitted_date`, `submitted_by_user_id`, and `rejection_reason` to null for another attempt.

Amendment is how a filed-and-accepted report is corrected. A `ComplianceOfficer` creates an amendment against an `ACCEPTED` report — any other state is refused with `ERR_REPORT_NOT_ACCEPTED` — carrying `expected_report_version` for the §2.7 concurrency check, which is evaluated before the `ACCEPTED`-state check, and at most one pending amendment, meaning one in `DRAFT` or `SUBMITTED`, may exist per superseded report (else `ERR_PENDING_AMENDMENT_EXISTS`). The amendment is a new `DRAFT` report for the same state and report year, its `supersedes_report_id` pointing at the report it amends, with every non-`REMOVED` line of the prior report copied in as a fresh `INCLUDED` line and the copied totals recomputed; the superseded report's `version` increments at amendment creation, though it remains `ACCEPTED` until the amendment itself is accepted. The amendment then lives the ordinary report lifecycle — lines, submission, state review — and its acceptance is what finally moves the prior head to `SUPERSEDED`.

### 3.5. Securities Valuation and Liquidation

Brokerage property carries an extra evidentiary layer. A `ComplianceOfficer` registers a **securities detail** on a property whose type is `BROKERAGE_SHARES` — attempting it on any other property type is refused with `ERR_NOT_SECURITIES_PROPERTY` — supplying the `cusip` (a CUSIP or ticker identifier), the `shares_quantity` in whole shares greater than zero, the `last_close_price_cents` per share at zero or more, and the `accrued_dividends_cents` of unpaid dividends at zero or more. The relationship is one-to-one: a property that already has a detail refuses a second with `ERR_SECURITIES_DETAIL_EXISTS`. The detail starts `REGISTERED`, and reading it back returns an array of zero or one element, never a bare object; the read is not paginated.

Securities are valued twice, by two variants that generally diverge. The **provisional** variant runs at line-item inclusion into a draft report and values the position at its last known close: the `last_close_price_cents` multiplied by the `shares_quantity`, plus the `accrued_dividends_cents`, with no fee deduction. The **final** variant runs at liquidation settlement and values the position at its actual execution: the `execution_price_cents_per_share` multiplied by the `shares_quantity`, minus the `liquidation_fee_cents`, plus the `accrued_dividends_cents`, floored at zero. All inputs are integer cents, so neither variant rounds.

Liquidation itself is a `TreasuryOps` workflow with its own small machine — `REQUESTED`, `EXECUTED`, then the terminal pair `SETTLED` and `CANCELLED`. Requesting an order takes a payload with the `property_id` and a `liquidation_fee_cents` of zero or more. The property must be `REPORTED` — meaning it rides an `ACCEPTED` report — else `ERR_PROPERTY_NOT_REPORTED`; it must be a `BROKERAGE_SHARES` property, else `ERR_NOT_SECURITIES_PROPERTY`; its securities detail must be present, else `ERR_SECURITIES_DETAIL_REQUIRED`; and no other non-terminal order — one in `REQUESTED` or `EXECUTED` — may exist for the property, else `ERR_DUPLICATE_ACTIVE_LIQUIDATION`. The order begins `REQUESTED`, with `executed_date`, `settled_date`, `gross_proceeds_cents`, and `net_proceeds_cents` all null.

Executing an order takes the actual `execution_price_cents_per_share`, an integer of zero or more, and is gated three ways: the order must be `REQUESTED`, else `ERR_LIQUIDATION_INVALID_STATE`; the execution may occur no later than sixty days after the `due_date` of the accepted report containing the property — a clock date on or before that day passes, anything later is refused with `ERR_LIQUIDATION_WINDOW_VIOLATION`; and the fee may not exceed the gross plus dividends, so a `liquidation_fee_cents` greater than the execution price times the share quantity plus the `accrued_dividends_cents` is refused with `ERR_LIQUIDATION_FEE_EXCEEDS_GROSS`, with equality expressly allowed since net proceeds floor at zero. Execution stamps `executed_date` with the clock date, computes `gross_proceeds_cents` as the execution price times the `shares_quantity`, and stages the detail: `REGISTERED → EXECUTION_PENDING`, with `pending_execution_price_cents` holding the execution price.

Settlement is where value becomes final. Settling an `EXECUTED` order — any other state is `ERR_LIQUIDATION_INVALID_STATE` — stamps `settled_date` with the clock date and computes `net_proceeds_cents` as the greater of zero and the gross proceeds minus the `liquidation_fee_cents` plus the `accrued_dividends_cents`. The cascade then runs four hops: the property's `INCLUDED` report line moves to `FINAL` with its `final_value_cents` set to the `net_proceeds_cents`; the containing report recomputes `total_final_cents` — `total_provisional_cents` is unchanged — and its `version` increments; any `PENDING` remittance for that report recomputes its `variance_cents` against the new final total; and the securities detail moves to `LIQUIDATED` with `pending_execution_price_cents` cleared to null.

Cancellation compensates rather than deletes. Cancelling from `REQUESTED` simply moves the order to `CANCELLED`. Cancelling from `EXECUTED` — the same `ERR_LIQUIDATION_INVALID_STATE` guards any other origin — runs a compensating reversal: the detail returns `EXECUTION_PENDING → REGISTERED`, its `pending_execution_price_cents` clears to null, and, as the compensating invariant, the report line's `provisional_value_cents` and status are left exactly as they were, so an included securities line survives a cancelled execution with its provisional value intact.

### 3.6. Remittance and the Transfer of Custody

Once a report is accepted, the holder pays the state. A `TreasuryOps` operator creates a **remittance** against an `ACCEPTED` report — any other report state is refused with `ERR_REPORT_NOT_ACCEPTED` — supplying the `amount_cents`, an integer of zero or more. Only one `PENDING` remittance may exist per report; a second attempt is refused with `ERR_REMITTANCE_ALREADY_PENDING`. The remittance begins `PENDING` with `confirmed_date` and `variance_cents` null. Deliberately, neither the all-final check nor the variance check runs at creation — both are confirm-time gates, so a holder may stage a remittance while securities liquidation is still in flight.

Confirmation is the state's receipt. A `StateAuditor` confirms a remittance that is `PENDING` (else `ERR_REMITTANCE_NOT_PENDING`), but only when every non-`REMOVED` line of the report has reached `FINAL` (else `ERR_LINES_NOT_FINAL`) and the `variance_cents` — the `amount_cents` minus the report's `total_final_cents`, evaluated at confirm time — is exactly zero (else `ERR_REMITTANCE_VARIANCE_NONZERO`); the freshly evaluated variance is recorded on the remittance either way, so even a refused confirmation updates the visible `variance_cents`. On confirmation the `confirmed_date` is stamped with the clock date, the report's `confirmed_remittance_cents` increases by the confirmed `amount_cents` with its `version` incrementing, and every property with an `INCLUDED` or `FINAL` line in the report advances `REPORTED → REMITTED`.

Failure and recovery are first-class. A `StateAuditor` may fail a `PENDING` remittance — again `ERR_REMITTANCE_NOT_PENDING` guards the origin state — moving it to `FAILED` and recording the supplied `failure_reason`. A `TreasuryOps` operator may then requeue a `FAILED` remittance — any other origin is `ERR_REMITTANCE_NOT_FAILED` — supplying a corrected `amount_cents`; the requeue replaces the amount, clears the `failure_reason` to null, clears `variance_cents` to null, and returns the remittance to `PENDING`; the variance is recomputed at the next confirmation. `CONFIRMED` is the remittance's terminal state.

Custody itself is transferred by the state. Once a property stands `REMITTED`, a `StateAuditor` escheats it — the formal taking of custody — moving it `REMITTED → ESCHEATED` and stamping `escheated_date` with the clock date; a property in any other state is refused with `ERR_PROPERTY_NOT_REMITTED`. Even after escheatment the story is not over: §3.7's claim pipeline can still reunite the property with its owner from `ESCHEATED` exactly as from `REMITTED`.

### 3.7. Owner Claims and Reunification

The owner's road back begins with a claim. A `Claimant` files through a payload naming the `property_id` and, optionally, an `evidence_ref`. The claim's `claimant_owner_id` is set to the filer's `X-User-ID` and must equal the property's owner — a claimant touching another owner's property is refused with `ERR_OWNERSHIP_SCOPE_VIOLATION`. The property must stand `REMITTED` or `ESCHEATED`, else `ERR_PROPERTY_NOT_CLAIMABLE`. At most one non-terminal claim — one in `SUBMITTED`, `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `APPROVED` — may exist per property, else `ERR_DUPLICATE_ACTIVE_CLAIM`. And there must be something to recover: the recoverable base — the property's remitted line value for cash, or its settled liquidation net proceeds for securities, exactly the base the payout computation below will use — must be greater than zero, so a claim on a position liquidated to zero net proceeds is refused with `ERR_CLAIM_EXCEEDS_RECOVERABLE`, as is a property for which no such base can be determined at all. The claim's `claim_type` is derived — `SECURITIES` for a `BROKERAGE_SHARES` property, otherwise `CASH` — and the claim begins `SUBMITTED`. The claims listing is staff-only, open to `ComplianceOfficer`, `ClaimsExaminer`, and `ClaimsApprover`, filterable by `property_id` and `status`; a claimant reaches their own claims through the owner's claims listing instead.

Review is a two-chair discipline. A `ClaimsExaminer` opens review on a `SUBMITTED` claim — any other state is `ERR_CLAIM_NOT_SUBMITTED` — moving it to `UNDER_REVIEW` and recording their identity as `reviewed_by_user_id`. The examiner may request more information, supplying an `info_request_note`, which moves an `UNDER_REVIEW` claim (else `ERR_CLAIM_NOT_UNDER_REVIEW`) to `MORE_INFO_REQUESTED`. The claimant answers by submitting information with an `info_response_ref`; this is allowed only by the owning claimant (else `ERR_OWNERSHIP_SCOPE_VIOLATION`, checked first) and only from `MORE_INFO_REQUESTED` (else `ERR_CLAIM_NOT_AWAITING_INFO`), and returns the claim to `UNDER_REVIEW`.

Decision belongs to a different desk. A `ClaimsApprover` approves or denies an `UNDER_REVIEW` claim, and in both cases the approver's `X-User-ID` must differ from the recorded `reviewed_by_user_id` — the same person may never examine and decide — else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Approval additionally requires the property to still stand `REMITTED` or `ESCHEATED` (else `ERR_PROPERTY_NOT_CLAIMABLE`); it computes the payout, recording `approved_base_cents`, `approved_interest_cents`, `processing_fee_cents`, and `approved_payout_cents`, and captures the approver as `decided_by_user_id`. Denial records the supplied `denial_reason` and likewise captures `decided_by_user_id`; `DENIED` is terminal.

The payout is computed in a pinned order — this ordering is what resolves the apparent circularity between the fee and the gross it is levied on. First, the base: for a `CASH` claim, the `final_value_cents` of the property's `FINAL` line in the `ACCEPTED` — possibly since `SUPERSEDED` — report that carried it; for a `SECURITIES` claim, the `net_proceeds_cents` of the property's `SETTLED` liquidation order. Second, interest: for `CASH`, the base multiplied by the applicable rule's `annual_interest_rate_bp` (treated as zero when the property no longer has an applicable rule at approval time) and by the days held, divided by 3,650,000, and rounded half-up to whole cents, where the days held run from the confirming remittance's `confirmed_date` to the approval date and never below zero (when several confirmed remittances qualify, the most recently confirmed supplies the date; when none is found, the days held are zero); for `SECURITIES`, always zero — states return liquidation proceeds without interest, so identical bases still yield different payouts across the two variants whenever the days held are positive. Third, the gross is the base plus the interest. Fourth, the fee tier is selected by that gross: the processing fee applies only when the gross exceeds 100000 cents — one thousand dollars — and a gross at or below that cap pays no fee. Fifth, the `processing_fee_cents` is the gross multiplied by 150 basis points — one and a half percent — rounded half-up to whole cents when the tier applies, and zero otherwise. Sixth and last, the `approved_payout_cents` is the gross minus the `processing_fee_cents`.

Disbursement closes the loop. A `TreasuryOps` operator pays an `APPROVED` claim — any other state is `ERR_CLAIM_NOT_APPROVED` — stamping `paid_date` with the clock date, moving the claim to its terminal `PAID` state, and cascading to the property: `REMITTED → REUNITED` or `ESCHEATED → REUNITED`, with `reunited_date` set to the clock date. A claimant who thinks better of it may withdraw, but only their own claim (else `ERR_OWNERSHIP_SCOPE_VIOLATION`, checked first) and only from `SUBMITTED` or `MORE_INFO_REQUESTED` (else `ERR_CLAIM_NOT_WITHDRAWABLE`), moving it to the terminal `WITHDRAWN`.

### 3.8. Late Filing Exposure: Penalties, Interest, and State Audits

Lateness has a price, and the state names it through a **penalty assessment**. A `StateAuditor` assesses a report that is `SUBMITTED` or `ACCEPTED` — any other state is refused with `ERR_REPORT_NOT_SUBMITTED` — and at most one active assessment, meaning one in `ASSESSED` or `DISPUTED`, may exist per report (else `ERR_PENALTY_ALREADY_ASSESSED`). Creation stamps `assessed_date` with the clock date and computes `days_late`, `penalty_cents`, `interest_cents`, and their sum `total_cents`; the assessment begins `ASSESSED`, with `waiver_reason` and `dispute_reason` null.

The `days_late` is the number of whole days from the report's `due_date` to its `submitted_date`, floored at zero — a report submitted on or before its due date is never late, and both the penalty and the interest of such a report are zero. Otherwise the penalty picks its rate by tier: from one day late up to the rule's `gross_negligence_day_threshold` the per-day rate is `daily_penalty_cents`; once the days late run strictly beyond that threshold, the `gross_daily_penalty_cents` rate applies — and it applies to every day late, not merely to the days past the threshold. The raw penalty is the selected rate times the days late. The cap is `penalty_cap_pct` percent of the report's `total_provisional_cents`, computed with floor rounding to whole cents, and the `penalty_cents` is the lesser of the raw amount and the cap. The rates and caps come from the dormancy rule for the report's state and the property type of the report's first `INCLUDED` line — the earliest-created one — and every line on a report shares one state, so a single rule supplies the schedule. If that lookup finds no applicable rule, any rule configured for the report's state supplies the schedule instead; if the state has no rule at all, both the penalty and the interest are zero.

Interest runs on a different clock: the days of interest count from the report's `due_date` to the `assessed_date` in whole days. For each line in the included set — `INCLUDED` or `FINAL` — the base is the line's `final_value_cents` when the line is `FINAL` and its `provisional_value_cents` otherwise; the line's interest is that base multiplied by the rule's `annual_interest_rate_bp` and by the days of interest, divided by 3,650,000, rounded half-up to whole cents. The assessment's `interest_cents` is the sum of those per-line amounts, and the rounding order is pinned: each line is rounded first and the rounded amounts are then summed, never the reverse.

From `ASSESSED`, three roads diverge. A `TreasuryOps` operator pays the assessment, moving it to the terminal `PAID` — any origin other than `ASSESSED` is refused with `ERR_PENALTY_NOT_ASSESSED`. A `ComplianceOfficer` disputes an `ASSESSED` assessment — any other origin is refused with `ERR_PENALTY_NOT_ASSESSED` — recording a `dispute_reason` and moving it to `DISPUTED`. And a `StateAuditor` may waive an assessment from either `ASSESSED` or `DISPUTED` — any other origin is likewise refused with `ERR_PENALTY_NOT_ASSESSED` — recording a `waiver_reason` and moving it to the terminal `WAIVED`; a dispute that does not persuade is instead upheld — a `StateAuditor` returns a `DISPUTED` assessment to `ASSESSED`, with any other origin refused as `ERR_PENALTY_NOT_DISPUTED`.

Beyond penalties lie audits. A `StateAuditor` opens an **audit case** with a `state_code` and a closed lookback window from `lookback_start_year` through `lookback_end_year`, both positive integers and both years inclusive, the end year never before the start — an end year before the start year is rejected as `ERR_INVALID_REQUEST`. Two non-`CLOSED` audits for the same state may not hold overlapping lookback windows, and touching counts as overlap — a shared boundary year is already an intersection — else `ERR_AUDIT_LOOKBACK_OVERLAP`. The case opens `OPENED` and advances one step per call along `OPENED → FIELDWORK → FINDINGS_ISSUED → CLOSED`; advancing a `CLOSED` case is impossible and is refused with `ERR_AUDIT_CASE_NOT_ADVANCEABLE`. The audits listing may be filtered by `state_code` and `status`.

The step from `FIELDWORK` to `FINDINGS_ISSUED` is where exposure is quantified, and the result is stored as `estimated_exposure_cents`. The candidate set is every property of the audit's state whose status is `DORMANT`, `DUE_DILIGENCE`, or `REPORTABLE`, whose `dormancy_date` falls within the closed interval from January 1 of the start year through December 31 of the end year, and which has no line in `INCLUDED` or `FINAL` status in any `SUBMITTED` or `ACCEPTED` report. For each candidate, under its applicable dormancy rule: the missed due date is the report-window derivation of §3.2 taken without the roll-forward — the first eligible cycle's due date, even though it has passed; the days past due run from that missed date to the current date, floored at zero; the candidate's penalty is the applicable per-day rate — `daily_penalty_cents` while the days past due are at or below the `gross_negligence_day_threshold`, `gross_daily_penalty_cents` beyond it — times the days past due, capped at the floor of `penalty_cap_pct` percent of the property's `original_value_cents`; the candidate's interest is its `original_value_cents` times the `annual_interest_rate_bp` times the days past due, divided by 3,650,000 and rounded half-up to whole cents; and the candidate's exposure is its `original_value_cents` plus its penalty plus its interest. The estimate is the sum over all candidates, and an empty candidate set yields zero; a candidate with no applicable dormancy rule is passed over and contributes nothing. Candidates are processed in order of earliest `dormancy_date` first, with ties broken by `created_at` ascending — an ordering that does not affect the sum. A dedicated computed read of the exposure returns the `estimated_exposure_cents` together with the `candidate_property_ids` behind it. The audit's own `estimated_exposure_cents` stays null until the findings step stores it; the exposure read returns that stored snapshot once findings are issued, and before that computes the same estimate live against current state without storing it.

### 3.9. Evidentiary Records and Retention

Every artifact the pipeline produces — the letter copy, the filed report, the claim evidence, the remittance receipt — must be retained for its statutory period and only then destroyed. A `ComplianceOfficer` registers a **document record** with an `artifact_type` of `LETTER_COPY`, `REPORT_FILE`, `CLAIM_EVIDENCE`, or `REMITTANCE_RECEIPT`; a `related_entity_type` naming the artifact's owner — one of `DueDiligenceLetter`, `HolderReport`, `OwnerClaim`, or `Remittance`; and the `related_entity_id` of that owner. The reference is polymorphic: the server performs no existence validation on it. Registration computes the `retention_until` as the creation date plus the retention years for the artifact type — five years for `LETTER_COPY`, seven for `CLAIM_EVIDENCE`, ten for `REPORT_FILE`, and ten for `REMITTANCE_RECEIPT` — and the record begins `REGISTERED` with `purged_at` null.

Destruction is gated and permanent in name only. A `HolderAdmin` purges a record that is still `REGISTERED` — a second purge is refused with `ERR_DOCUMENT_ALREADY_PURGED` — and only once the logical clock date has reached the `retention_until`: an earlier attempt is refused with `ERR_RETENTION_PERIOD_NOT_ELAPSED`, while a purge landing exactly on the `retention_until` date is allowed. Purging stamps `purged_at` with the clock datetime and moves the record `REGISTERED → PURGED`, its terminal state. The purge is a soft delete: purged records disappear from the document listing unless the caller passes `include_purged` set to true, and they remain readable by their `id`. The listing may also be filtered by `artifact_type`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (e.g., an owner, a holder report) or add new member resources to a collection (e.g., a line item to a report, a contact event to a property) return a `201 Created` status code. Operations that modify an existing resource — state transitions, updates, sweeps — and all retrievals return a `200 OK` status code. Request payloads, response contents, and side effects for each operation are specified by the narratives of §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/escheatment/owners` | Register an owner | ComplianceOfficer |
| GET | `/escheatment/owners` | List owners (paginated) | Any |
| GET | `/escheatment/owners/{ownerId}` | Get one owner (Claimant: only own id) | Any, Claimant |
| GET | `/escheatment/owners/{id}/properties` | List an owner's properties | Any, Claimant |
| GET | `/escheatment/owners/{id}/owner-claims` | List claims filed by an owner | Any, Claimant |
| POST | `/escheatment/dormancy-rules` | Create a dormancy rule for (state_code, property_type) | HolderAdmin |
| GET | `/escheatment/dormancy-rules` | List dormancy rules | Any |
| GET | `/escheatment/dormancy-rules/{ruleId}` | Get one dormancy rule | Any |
| PUT | `/escheatment/dormancy-rules/{ruleId}` | Update a dormancy rule; window overlap re-validated | HolderAdmin |
| POST | `/escheatment/properties` | Register a property | ComplianceOfficer |
| GET | `/escheatment/properties` | List properties | Any |
| GET | `/escheatment/properties/{propertyId}` | Get one property (Claimant: only own) | Any, Claimant |
| POST | `/escheatment/properties/{propertyId}/reactivate` | Reactivate a dormant-pipeline property with contact evidence | ComplianceOfficer |
| POST | `/escheatment/properties/{propertyId}/contact-events` | Record an owner contact (Claimant: only for own property) | ComplianceOfficer, Claimant |
| GET | `/escheatment/properties/{id}/contact-events` | List contact events for a property | Any |
| GET | `/escheatment/properties/{id}/report-line-items` | List report line items referencing a property | Any |
| GET | `/escheatment/properties/{id}/owner-claims` | List claims filed against a property | Any |
| POST | `/escheatment/properties/{propertyId}/escheat` | State takes custody of a REMITTED property | StateAuditor |
| POST | `/escheatment/properties/{propertyId}/due-diligence-letters` | Send a due-diligence letter (created SENT) | ComplianceOfficer |
| GET | `/escheatment/properties/{id}/due-diligence-letters` | List letters for a property | Any |
| GET | `/escheatment/due-diligence-letters/{letterId}` | Get one letter | Any |
| POST | `/escheatment/due-diligence-letters/{letterId}/mark-delivered` | Mark a letter delivered | ComplianceOfficer |
| POST | `/escheatment/due-diligence-letters/{letterId}/mark-undeliverable` | Mark a letter undeliverable; property becomes REPORTABLE | ComplianceOfficer |
| POST | `/escheatment/due-diligence-letters/{letterId}/record-response` | Record owner response with qualifying contact evidence | ComplianceOfficer |
| POST | `/escheatment/holder-reports` | Create a DRAFT report for (state_code, report_year) | ComplianceOfficer |
| GET | `/escheatment/holder-reports` | List reports | Any |
| GET | `/escheatment/holder-reports/{reportId}` | Get one report | Any |
| POST | `/escheatment/holder-reports/{reportId}/amendments` | Create an amendment DRAFT superseding an ACCEPTED report (OCC) | ComplianceOfficer |
| GET | `/escheatment/holder-reports/{id}/amendments` | List amendment reports superseding this report | Any |
| POST | `/escheatment/holder-reports/{reportId}/line-items` | Add a REPORTABLE property to a DRAFT report (OCC) | ComplianceOfficer |
| GET | `/escheatment/holder-reports/{id}/line-items` | List a report's line items | Any |
| POST | `/escheatment/holder-reports/{reportId}/line-items/{lineId}/remove` | Remove an INCLUDED line from a DRAFT report | ComplianceOfficer |
| POST | `/escheatment/holder-reports/{reportId}/submit` | Submit a DRAFT report; cash lines finalize | ComplianceOfficer |
| POST | `/escheatment/holder-reports/{reportId}/accept` | State accepts a SUBMITTED report (acceptor differs from submitter) | StateAuditor |
| POST | `/escheatment/holder-reports/{reportId}/reject` | State rejects a SUBMITTED report | StateAuditor |
| POST | `/escheatment/holder-reports/{reportId}/reopen` | Reopen a REJECTED report back to DRAFT | ComplianceOfficer |
| POST | `/escheatment/properties/{propertyId}/securities-detail` | Register securities detail on a BROKERAGE_SHARES property (1:1) | ComplianceOfficer |
| GET | `/escheatment/properties/{id}/securities-detail` | Get the securities detail for a property (array of 0 or 1) | Any |
| POST | `/escheatment/liquidation-orders` | Request liquidation of a REPORTED securities property | TreasuryOps |
| GET | `/escheatment/liquidation-orders/{orderId}` | Get one liquidation order | Any |
| GET | `/escheatment/properties/{id}/liquidation-orders` | List liquidation orders for a property | Any |
| POST | `/escheatment/liquidation-orders/{orderId}/execute` | Execute a REQUESTED order at an actual price | TreasuryOps |
| POST | `/escheatment/liquidation-orders/{orderId}/settle` | Settle an EXECUTED order; finalizes line value | TreasuryOps |
| POST | `/escheatment/liquidation-orders/{orderId}/cancel` | Cancel a REQUESTED or EXECUTED order | TreasuryOps |
| POST | `/escheatment/holder-reports/{reportId}/remittances` | Create a PENDING remittance for an ACCEPTED report | TreasuryOps |
| GET | `/escheatment/holder-reports/{id}/remittances` | List remittances for a report | Any |
| GET | `/escheatment/remittances/{remittanceId}` | Get one remittance | Any |
| POST | `/escheatment/remittances/{remittanceId}/confirm` | State confirms a PENDING remittance when variance is exactly 0 | StateAuditor |
| POST | `/escheatment/remittances/{remittanceId}/fail` | State marks a PENDING remittance failed | StateAuditor |
| POST | `/escheatment/remittances/{remittanceId}/requeue` | Requeue a FAILED remittance with a corrected amount | TreasuryOps |
| POST | `/escheatment/owner-claims` | Claimant files a claim on an owned REMITTED/ESCHEATED property | Claimant |
| GET | `/escheatment/owner-claims` | List claims (staff roles) | ComplianceOfficer, ClaimsExaminer, ClaimsApprover |
| GET | `/escheatment/owner-claims/{claimId}` | Get one claim (Claimant: only own) | Any, Claimant |
| POST | `/escheatment/owner-claims/{claimId}/start-review` | Examiner opens review on a SUBMITTED claim | ClaimsExaminer |
| POST | `/escheatment/owner-claims/{claimId}/request-info` | Examiner requests more information | ClaimsExaminer |
| POST | `/escheatment/owner-claims/{claimId}/submit-info` | Claimant supplies requested information | Claimant |
| POST | `/escheatment/owner-claims/{claimId}/approve` | Approver approves a reviewed claim; payout computed | ClaimsApprover |
| POST | `/escheatment/owner-claims/{claimId}/deny` | Approver denies a reviewed claim | ClaimsApprover |
| POST | `/escheatment/owner-claims/{claimId}/pay` | Disburse an APPROVED claim; property reunites | TreasuryOps |
| POST | `/escheatment/owner-claims/{claimId}/withdraw` | Claimant withdraws a SUBMITTED or MORE_INFO_REQUESTED claim | Claimant |
| POST | `/escheatment/holder-reports/{reportId}/penalty-assessments` | Assess late penalty + interest on a SUBMITTED/ACCEPTED report | StateAuditor |
| GET | `/escheatment/holder-reports/{id}/penalty-assessments` | List penalty assessments for a report | Any |
| GET | `/escheatment/penalty-assessments/{assessmentId}` | Get one penalty assessment | Any |
| POST | `/escheatment/penalty-assessments/{assessmentId}/pay` | Pay an ASSESSED penalty | TreasuryOps |
| POST | `/escheatment/penalty-assessments/{assessmentId}/waive` | State waives an ASSESSED or DISPUTED penalty | StateAuditor |
| POST | `/escheatment/penalty-assessments/{assessmentId}/dispute` | Holder disputes an ASSESSED penalty | ComplianceOfficer |
| POST | `/escheatment/penalty-assessments/{assessmentId}/uphold` | State upholds a DISPUTED penalty (returns to ASSESSED) | StateAuditor |
| POST | `/escheatment/audit-cases` | Open a state audit with a closed-interval lookback window | StateAuditor |
| GET | `/escheatment/audit-cases` | List audit cases | Any |
| GET | `/escheatment/audit-cases/{auditId}` | Get one audit case | Any |
| POST | `/escheatment/audit-cases/{auditId}/advance` | Advance the audit one step; FINDINGS_ISSUED computes exposure | StateAuditor |
| GET | `/escheatment/audit-cases/{auditId}/exposure` | Computed read of the exposure estimate | Any |
| POST | `/escheatment/document-records` | Register a retained artifact; retention computed | ComplianceOfficer |
| GET | `/escheatment/document-records` | List document records; PURGED excluded unless include_purged=true | Any |
| GET | `/escheatment/document-records/{docId}` | Get one document record (PURGED still readable by id) | Any |
| POST | `/escheatment/document-records/{docId}/purge` | Purge a record whose retention window has fully elapsed | HolderAdmin |
| POST | `/escheatment/_clock/set_current_utc` | Set the server's logical clock (ISO8601 UTC) | HolderAdmin |
| POST | `/escheatment/_sweeps/dormancy` | Run the dormancy/letter sweep against the logical clock | HolderAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is only an index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_DORMANCY_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTACT_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_LETTER_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_SECURITIES_DETAIL_NOT_FOUND` | 404 Not Found |
| `ERR_LIQUIDATION_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_REMITTANCE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_PENALTY_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROPERTY_NOT_DORMANT` | 409 Conflict |
| `ERR_PROPERTY_NOT_REACTIVATABLE` | 409 Conflict |
| `ERR_PROPERTY_NOT_REMITTED` | 409 Conflict |
| `ERR_LETTER_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_REPORT_NOT_DRAFT` | 409 Conflict |
| `ERR_REPORT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_REPORT_NOT_REJECTED` | 409 Conflict |
| `ERR_REPORT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_LINE_ITEM_NOT_REMOVABLE` | 409 Conflict |
| `ERR_LIQUIDATION_INVALID_STATE` | 409 Conflict |
| `ERR_REMITTANCE_NOT_PENDING` | 409 Conflict |
| `ERR_REMITTANCE_NOT_FAILED` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_AWAITING_INFO` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_CLAIM_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_PENALTY_NOT_ASSESSED` | 409 Conflict |
| `ERR_PENALTY_NOT_DISPUTED` | 409 Conflict |
| `ERR_AUDIT_CASE_NOT_ADVANCEABLE` | 409 Conflict |
| `ERR_DOCUMENT_ALREADY_PURGED` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_LETTER` | 409 Conflict |
| `ERR_DORMANCY_RULE_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_LOOKBACK_OVERLAP` | 409 Conflict |
| `ERR_SECURITIES_DETAIL_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 Conflict |
| `ERR_PENDING_AMENDMENT_EXISTS` | 409 Conflict |
| `ERR_REMITTANCE_ALREADY_PENDING` | 409 Conflict |
| `ERR_PENALTY_ALREADY_ASSESSED` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CLAIM` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_LIQUIDATION` | 409 Conflict |
| `ERR_DUE_DILIGENCE_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_LIQUIDATION_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_RETENTION_PERIOD_NOT_ELAPSED` | 409 Conflict |
| `ERR_NO_APPLICABLE_DORMANCY_RULE` | 422 Unprocessable Entity |
| `ERR_PROPERTY_NOT_REPORTED` | 422 Unprocessable Entity |
| `ERR_NOT_SECURITIES_PROPERTY` | 422 Unprocessable Entity |
| `ERR_LINES_NOT_FINAL` | 422 Unprocessable Entity |
| `ERR_DUE_DILIGENCE_NOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_OWNER_STATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PROPERTY_NOT_REPORTABLE` | 422 Unprocessable Entity |
| `ERR_PROPERTY_NOT_CLAIMABLE` | 422 Unprocessable Entity |
| `ERR_SECURITIES_DETAIL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CONTACT_EVENT_PROPERTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CONTACT_NOT_QUALIFYING` | 422 Unprocessable Entity |
| `ERR_PROPERTY_IN_SUBMITTED_REPORT` | 409 Conflict |
| `ERR_EMPTY_REPORT` | 422 Unprocessable Entity |
| `ERR_DUE_DILIGENCE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_REMITTANCE_VARIANCE_NONZERO` | 422 Unprocessable Entity |
| `ERR_LIQUIDATION_FEE_EXCEEDS_GROSS` | 422 Unprocessable Entity |
| `ERR_CLAIM_EXCEEDS_RECOVERABLE` | 422 Unprocessable Entity |
