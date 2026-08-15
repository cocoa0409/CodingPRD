# Patient Experience Survey API — Product Requirements Document

## 1. Introduction

Hospitals participating in the CMS HCAHPS program depend on a disciplined survey administration pipeline: which discharges are eligible to be sampled, which vendor mails or calls the patient, whether responses arrive before the fielding window closes, and how the resulting top-box scores roll up into star ratings and value-based purchasing adjustments. This document specifies the Patient Experience Survey API, a system that administers that pipeline end to end — program and vendor setup, discharge eligibility screening, sample creation, response intake and adjudication, scoring, publication, improvement-initiative tracking, comment routing, and survey mode-transition analysis.

The platform is organized around the **survey cycle**. A cycle's posture gates nearly every operation: sampling is possible only while sampling is open, responses are accepted only during fielding, adjudication happens only during reconciliation, and the public artifacts of a cycle — star ratings, attribution reports, value-based purchasing projections — exist only once the cycle has been scored. Derived counters and rates are recomputed immediately on every mutation, so reading a cycle always reflects the current truth. Every date- and time-sensitive decision in the system is driven by a server-maintained logical clock rather than the wall clock, keeping the entire pipeline deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API. All resource collections are mounted under `/api`; the only capability mounted elsewhere is the logical-clock control described in §2.4.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the user's operational capacity. The declared roles are `ProgramAdmin`, `DataSteward`, `VendorOperator`, and `UnitManager`. (`Any` is a pseudo-role used in this document to mark read-only endpoints that every authenticated role may call; it is not a real role value.) A request missing either header, or carrying a role that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity semantics differ per role:

- When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `DataSteward`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.
- When `X-User-Role` is `VendorOperator`, `X-User-ID` is the `id` of the acting `SurveyVendor`; ownership checks on any resource that references a `SurveyVendor` compare the resource's `vendor_id` field to `X-User-ID`. A vendor operator submitting a response or a delivery disposition for a case whose `vendor_id` does not equal `X-User-ID` is rejected with `ERR_VENDOR_CASE_MISMATCH` (HTTP 403).
- When `X-User-Role` is `UnitManager`, `X-User-ID` is the `id` of the acting `CareUnit`; ownership checks on service-recovery work compare the ticket's `unit_id` — or the requested `unit_id` at ticket creation — to `X-User-ID`. A unit manager operating on a ticket of another unit is rejected with `ERR_UNIT_ACCESS_DENIED` (HTTP 403).

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

List endpoints accept two query parameters. `limit` specifies the maximum number of items to return: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies the number of items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

The server maintains a logical clock that governs every temporal decision in the platform. At startup, before any explicit set, the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never fall back to the host wall clock. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`.

The logical clock stamps `received_at` on response intake, `superseded_at` on vendor supersession, `published_at` on cycle publication, `achieved_at` when an initiative reaches its target, and `acknowledged_at` when a service-recovery ticket is acknowledged. It also determines whether a response is late (`is_late`), gates the closing and reopening of fielding, and feeds the service-recovery SLA computation.

### 2.5. Common Resource Properties

All ten resources in the system — programs, vendors, cycles, care units, providers, discharges, sample cases, responses, improvement initiatives, and service-recovery tickets — share the same system-managed property set:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments on every mutation, including system-driven cascades such as counter recomputation.

### 2.6. Validation Order and Error Precedence

Every mutation request passes through a fixed validation pipeline. When several checks would fail, the earliest check in this order produces the error:

1. **Headers.** Presence and validity of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role permission.** The role is permitted on the endpoint (`ERR_FORBIDDEN_ROLE`).
3. **Entity-backed ownership.** `VendorOperator` and `UnitManager` identity matching (`ERR_VENDOR_CASE_MISMATCH`, `ERR_UNIT_ACCESS_DENIED`).
4. **Existence.** Path resource identifiers exist, validated left to right (`ERR_NOT_FOUND`).
5. **Request shape.** Required fields present, unknown fields rejected, types correct, enum members valid, dates ISO-formatted, composite scores within 1 to 4 (`ERR_INVALID_REQUEST`).
6. **Optimistic concurrency.** Where a version field is required (see §2.10), it is checked here, before any business rule (`ERR_STALE_PROGRAM_VERSION`).
7. **State-machine preconditions.** The target transition's posture and entity-state guards (the `ERR_CYCLE_*` family, `ERR_NO_ACTIVE_VENDOR`, `ERR_NO_CASES_SAMPLED`, `ERR_UNADJUDICATED_RESPONSES`, `ERR_CASE_NOT_IN_FIELD`, the `ERR_RESPONSE_*` family, the `ERR_TICKET_*` family, `ERR_DISCHARGE_LOCKED_BY_SAMPLE`, `ERR_BASELINE_CYCLE_NOT_PUBLISHED`, `ERR_INVALID_STATE`). Within this tier, cycle-posture errors are checked before entity-local state errors, so, for example, a closed cycle surfaces its `ERR_CYCLE_NOT_FIELDING` rather than a case-level error.
8. **Patient protection.** Only `ELIGIBLE` discharges may be sampled (`ERR_DISCHARGE_NOT_ELIGIBLE`).
9. **Referential scope.** Body-referenced resources belong to the same program aggregate (`ERR_CROSS_PROGRAM_REFERENCE`, `ERR_UNIT_RESPONSE_MISMATCH`).
10. **Temporal windows.** Fielding-window conflicts, sampling-window membership, clock gates, initiative window arithmetic (`ERR_CYCLE_WINDOW_OVERLAP`, `ERR_DISCHARGE_OUTSIDE_WINDOW`, `ERR_FIELDING_WINDOW_NOT_CLOSED`, `ERR_REOPEN_WINDOW_EXPIRED`, `ERR_INVALID_EVALUATION_CYCLE`, `ERR_INITIATIVE_WINDOW_OVERLAP`).
11. **Uniqueness, quota, and format constraints.** (`ERR_DUPLICATE_UNIT_CODE`, `ERR_DUPLICATE_CYCLE_INDEX`, `ERR_DUPLICATE_NPI`, `ERR_DISCHARGE_ALREADY_SAMPLED`, `ERR_SAMPLE_TARGET_REACHED`, `ERR_MODE_NOT_ALLOWED`, `ERR_RESPONSE_ALREADY_EXISTS`, `ERR_NO_COMMENT_TO_ROUTE`, `ERR_BELOW_PUBLICATION_THRESHOLD`).
12. **Fiscal.** The vendor budget check comes last (`ERR_VENDOR_BUDGET_EXCEEDED`).

### 2.7. Cycle Posture as the Master Gate

A `SurveyCycle` moves through `DRAFT`, `SAMPLING_OPEN`, `FIELDING`, `RECONCILIATION`, `SCORING`, and the terminal states `PUBLISHED` and `VOIDED`. This posture is the master gate for child operations across the platform. Creating sample cases requires `SAMPLING_OPEN`. Response intake and undeliverable marking require `FIELDING`. Adjudication of late responses requires `RECONCILIATION`; voiding an accepted response requires `FIELDING` or `RECONCILIATION`. Star ratings, attribution reports, and value-based purchasing projections are available only once a cycle has reached `SCORING` or `PUBLISHED`; mode-transition analysis compares two `PUBLISHED` cycles. A child operation attempted under the wrong posture is rejected with the corresponding cycle-posture error rather than any entity-local error, per §2.6.

### 2.8. The Vendor Budget Ledger

Each `SurveyVendor` carries a per-cycle administration budget. `cycle_budget_remaining_cents` is derived, never set directly: it equals `cycle_budget_cents` minus the sum of `postage_cost_cents` over every `SampleCase` referencing that vendor whose `billing_status` is `CHARGED`. Sampling a case charges the vendor; marking a case undeliverable, post-sample exclusion, and cycle voiding each issue a compensating credit by flipping the case's `billing_status` from `CHARGED` to `CREDITED`. The invariant is a compensating pair: a charge followed by its credit leaves `cycle_budget_remaining_cents` exactly unchanged, and at all times `cycle_budget_cents` equals `cycle_budget_remaining_cents` plus the sum of `CHARGED` postage. All budget arithmetic is exact integer cents.

### 2.9. Numeric Precision and Rounding

Percentages — response rates, top-box composite percentages, progress deltas, and the value-based purchasing adjustment — are rounded half-up to two decimal places. Mode-share deltas in the transition analysis are rounded half-up to four decimal places. Monetary values are integer cents and exact. Where a calculation produces per-line values that are later summed (the VBP projection), each line is rounded to a whole number before the sum; the rounding order is part of the contract. Threshold comparisons against stored two-decimal percentages are inclusive: a value exactly equal to the threshold satisfies it.

### 2.10. Optimistic Concurrency Control

Exactly one write operation in the API carries an optimistic-concurrency field: registering a vendor for a program. That request must include `expected_program_version`, a non-optional field carrying the `version` of the `SurveyProgram` the client last observed. If the program's current `version` has advanced since that observation, the request is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), and this check runs before any business rule, per §2.6. A successful vendor registration increments the program's `version` by 1. No other endpoint accepts a version field.

### 2.11. Resource Retrieval and List Filtering

For any endpoint whose path contains resource identifiers, the identifiers are validated left to right; the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource.

List endpoints support filtering by query parameter. Vendors filter by `program_id` and `status`; units and providers filter by `program_id`; discharges filter by `program_id`, `unit_id`, `provider_id`, and `status`; cycles filter by `program_id` and `status`; sample cases filter by `cycle_id`, `discharge_id`, `vendor_id`, `unit_id`, `provider_id`, and `status`; the responses of a case paginate with `limit` and `offset`; responses filter by `case_id`, `cycle_id`, `status`, and `mode_used`; initiatives filter by `unit_id`, `program_id`, `baseline_cycle_id`, `evaluation_cycle_id`, and `status`; service-recovery tickets filter by `unit_id`, `program_id`, `response_id`, and `status`.

## 3. Business Logic & Workflows

### 3.1. Program and Vendor Administration

A `ProgramAdmin` begins by creating a **survey program**, supplying a `name`, the `sampling_protocol` declared to CMS — one of `SIMPLE_RANDOM`, `STRATIFIED_BY_UNIT`, or `CENSUS` — and the vendor administration mode `admin_mode`, one of `MAIL_ONLY`, `PHONE_ONLY`, or `MIXED_MODE`. The administration mode constrains which survey mode may be assigned to sample cases later: a `MAIL_ONLY` program permits only `MAIL` cases, a `PHONE_ONLY` program permits only `PHONE` cases, and a `MIXED_MODE` program permits either. The program's `active_vendor_id` is an informational pointer to the currently `ACTIVE` vendor; it is null at creation and is not enforced as a foreign-key constraint.

Vendor registration is where program administration becomes concurrent. A `ProgramAdmin` registers a vendor with `program_id`, `name`, and `cycle_budget_cents` (an integer of at least 0). The new vendor starts `ACTIVE` with `cycle_budget_remaining_cents` equal to its full budget, and its creation supersedes the program's previously `ACTIVE` vendor: that vendor moves to `SUPERSEDED`, its `superseded_at` is stamped from the logical clock, and `active_vendor_id` swings to the new vendor. Because registration displaces an incumbent, the request must carry `expected_program_version` as described in §2.10; a client acting on a stale program version is rejected with `ERR_STALE_PROGRAM_VERSION`. A successful registration increments the program's `version` by 1.

A `ProgramAdmin` may also suspend a vendor. Suspension moves the vendor from `ACTIVE` to `SUSPENDED`; attempting it on a vendor in any other status is rejected with `ERR_INVALID_STATE`. When the suspended vendor was the program's only `ACTIVE` vendor, `active_vendor_id` is recomputed to null.

The program's organizational structure is flat. Care units are created with `program_id`, `name`, and a `unit_code` that must be unique within the program — a duplicate is rejected with `ERR_DUPLICATE_UNIT_CODE`. Providers are created with `program_id`, `full_name`, `npi`, and `specialty`, where `npi` must be unique within the program (`ERR_DUPLICATE_NPI`).

### 3.2. Discharge Intake and Exclusion Evaluation

A `DataSteward` feeds the discharge census. Each discharge is recorded with `program_id`, the patient's `mrn`, the attributing nursing `unit_id`, the attending `provider_id`, `admit_date`, `discharge_date` (which must be on or after `admit_date`), `discharge_disposition` (one of `HOME`, `SNF`, `EXPIRED`, `PSYCH_FACILITY`, `REHAB`, `HOSPICE`), `primary_dx_group` (one of `MEDICAL`, `SURGICAL`, `PSYCHIATRIC`, `MATERNITY`), `payer` (one of `MEDICARE`, `MEDICAID`, `COMMERCIAL`, `SELF_PAY`), `age_years` (at least 0), the mailing address's ISO 3166-1 alpha-2 `address_country`, the `no_publicity_flag` for patients who requested no contact, and `custody_status` (one of `NONE`, `LAW_ENFORCEMENT`). A new discharge lands in `ELIGIBILITY_PENDING` with an empty `exclusion_reasons` list.

For bulk feeds, a `DataSteward` submits a `count` (between 1 and 500) together with a shared `template` object carrying `mrn_prefix`, `unit_id`, `provider_id`, `admit_date`, `discharge_date`, `discharge_disposition`, `primary_dx_group`, `payer`, `age_years`, `address_country`, `no_publicity_flag`, and `custody_status`. Item *i* of the batch receives the `mrn` formed by appending a hyphen and the three-digit zero-padded sequence number to `mrn_prefix`, starting at 1. Every item is auto-evaluated against the exclusion rules below. The import is atomic: any malformed template field rejects the whole import. The result reports `created_count`, `eligible_count`, `excluded_count`, and the `discharge_ids` in creation order.

Eligibility evaluation applies nine exclusion rules to a single discharge. The reasons accumulate when: the disposition is `EXPIRED` (reason `EXPIRED`); the disposition is `SNF` (`SNF_DISCHARGE`); the disposition is `PSYCH_FACILITY` (`PSYCH_DISCHARGE`); the diagnosis group is `PSYCHIATRIC` (`PSYCH_DX`); the patient is younger than 18 (`MINOR`); the mailing address is outside the US (`NON_US_ADDRESS`); the patient requested no contact (`NO_PUBLICITY`); the patient is in law-enforcement custody (`CUSTODY`); or the stay involved no overnight, meaning `discharge_date` is on or before `admit_date` (`SHORT_STAY`). The resulting `exclusion_reasons` are stored sorted alphabetically for determinism. A discharge with any reasons becomes `EXCLUDED`; one with none becomes `ELIGIBLE`. Evaluation runs automatically per item inside the bulk import and on demand when a `DataSteward` evaluates a discharge, optionally supplying corrected source fields — any of `discharge_disposition`, `primary_dx_group`, `age_years`, `address_country`, `no_publicity_flag`, `custody_status`, `admit_date`, or `discharge_date` — which are applied before the rules re-run.

Re-evaluation is how errors are corrected, and it cascades. Moving a discharge from `ELIGIBLE` to `EXCLUDED` drives every linked sample case in `SAMPLED` or `IN_FIELD` to `EXCLUDED_POST_SAMPLE`; each such case still `CHARGED` flips to `CREDITED` and its `postage_cost_cents` are credited back to the vendor's `cycle_budget_remaining_cents`, and the cycle's counters are recomputed. When corrected fields are supplied, the override is blocked while any linked sample case has reached `RESPONDED`, surfacing `ERR_DISCHARGE_LOCKED_BY_SAMPLE`; a re-evaluation without overrides is always permitted. A discharge can also be reinstated from `EXCLUDED` to `ELIGIBLE` when the corrected data yields no reasons — but reinstatement does not resurrect a case already driven to `EXCLUDED_POST_SAMPLE`; post-sample exclusion is one-way.

### 3.3. Cycle Setup and Sampling

A `ProgramAdmin` defines a cycle with `program_id`, a human `label` such as 2026-Q3, a `cycle_index` (the program's quarter index, unique per program — duplicates are rejected with `ERR_DUPLICATE_CYCLE_INDEX` — and the basis for initiative window arithmetic), the sampling window `discharge_window_start` through `discharge_window_end`, the fielding window `fielding_start_date` through `fielding_end_date`, and a `target_sample_size` of at least 1. The fielding window is a closed interval, and it may not intersect the fielding window of any other non-`VOIDED` cycle of the same program — intervals that merely touch, sharing exactly one boundary date, count as conflicting and are rejected with `ERR_CYCLE_WINDOW_OVERLAP`. A new cycle starts in `DRAFT` with all derived counters at zero, a null `response_rate`, `publication_eligible` false, and every scored and published snapshot field null.

Opening sampling moves the cycle from `DRAFT` to `SAMPLING_OPEN`. The cycle must currently be `DRAFT` (otherwise `ERR_INVALID_STATE`), and the program must have an `ACTIVE` vendor (otherwise `ERR_NO_ACTIVE_VENDOR`), because cases cannot be charged without a vendor to bill.

With sampling open, a `DataSteward` samples a discharge into the cycle by supplying `cycle_id`, `discharge_id`, the `mode_assigned` (`MAIL` or `PHONE`), and the `postage_cost_cents` to charge (greater than 0). The guards, in the pipeline order of §2.6: the cycle must be `SAMPLING_OPEN` (`ERR_CYCLE_NOT_SAMPLING_OPEN`) and the program must still have an `ACTIVE` vendor (`ERR_NO_ACTIVE_VENDOR`); the discharge must be `ELIGIBLE` (`ERR_DISCHARGE_NOT_ELIGIBLE`); the discharge must belong to the same program as the cycle (`ERR_CROSS_PROGRAM_REFERENCE`); the `discharge_date` must fall within the cycle's sampling window, both boundaries inclusive (`ERR_DISCHARGE_OUTSIDE_WINDOW`); the discharge must not already be referenced by a sample case in any non-`VOIDED` cycle (`ERR_DISCHARGE_ALREADY_SAMPLED`); the `mode_assigned` must be permitted by the program's `admin_mode` (`ERR_MODE_NOT_ALLOWED`); the cycle must have remaining sample capacity, where the count of its cases in `SAMPLED`, `IN_FIELD`, `RESPONDED`, `NONRESPONSE`, or `UNDELIVERABLE` has not yet reached `target_sample_size` (`ERR_SAMPLE_TARGET_REACHED`); and the `postage_cost_cents` must not exceed the vendor's `cycle_budget_remaining_cents` (`ERR_VENDOR_BUDGET_EXCEEDED`).

Creation stamps the case with denormalized attribution: `vendor_id` is the snapshot of the program's `ACTIVE` vendor at that moment, and `unit_id` and `provider_id` are copied from the discharge. The case starts in `SAMPLED` with `billing_status` `CHARGED`, and the vendor's remaining budget drops by the postage amount, per the ledger invariant of §2.8.

Bulk sampling works the same way per item: a `DataSteward` supplies `cycle_id`, a `discharge_ids` list (between 1 and 500 entries, order preserved), and a shared `mode_assigned` and `postage_cost_cents`. The import is atomic — the first item failing a validation rejects the whole import with that item's error, and the budget check is applied per item in the listed order. The result reports `created_count` and the `sample_case_ids` in creation order.

Starting fielding moves the cycle from `SAMPLING_OPEN` to `FIELDING`; the cycle must be `SAMPLING_OPEN` (otherwise `ERR_CYCLE_NOT_SAMPLING_OPEN`) and at least one case must be in `SAMPLED` (otherwise `ERR_NO_CASES_SAMPLED`). Every `SAMPLED` case transitions to `IN_FIELD`, the cycle's `sampled_count` is frozen to the number of cases that entered the field, and the `eligible_denominator` is recomputed — those cases now count toward it.

### 3.4. Fielding Operations and Response Intake

While the cycle is `FIELDING`, a `VendorOperator` submits survey responses. Each intake names the `case_id`, the `mode_used` (`MAIL` or `PHONE` — the mode the response was actually collected in, which drives mode adjustment at scoring), and the four composite raw scores `nurse_comm_score`, `doctor_comm_score`, `cleanliness_score`, and `overall_rating_score`, each an integer from 1 to 4 where 4 is the top box; an optional `comment_text` carries free-text patient feedback. Intake is refused when the case is not `IN_FIELD` (`ERR_CASE_NOT_IN_FIELD`), when the cycle is not `FIELDING` (`ERR_CYCLE_NOT_FIELDING`), when the operator's `X-User-ID` does not equal the case's `vendor_id` (`ERR_VENDOR_CASE_MISMATCH`), or when the case already has a live response — one in `ACCEPTED`, `PENDING_REVIEW`, or `INCLUDED` (`ERR_RESPONSE_ALREADY_EXISTS`).

Accepted intake stamps `received_at` from the logical clock and denormalizes `cycle_id` from the case. Lateness is a pure function of the clock: when the calendar date of `received_at` falls after the cycle's `fielding_end_date`, the response is marked `is_late` and starts in `PENDING_REVIEW`; an on-time response starts in `ACCEPTED`. Either way the case moves from `IN_FIELD` to `RESPONDED`, `has_escalated_recovery` starts false, and the cycle's `completed_responses` is recomputed.

Bulk response intake mirrors this per item: `case_ids` (between 1 and 500, order preserved) with a shared `mode_used`, the four composite scores, and an optional `comment_text`; the import is atomic, and the result reports `created_count` and the `response_ids` in creation order.

Mail that comes back undeliverable is the vendor's responsibility to report. A `VendorOperator` marks a case undeliverable, moving it from `IN_FIELD` to `UNDELIVERABLE`; the case must be `IN_FIELD` (`ERR_CASE_NOT_IN_FIELD`), the cycle must be `FIELDING` (`ERR_CYCLE_NOT_FIELDING`), and the operator must own the case (`ERR_VENDOR_CASE_MISMATCH`). The case's `billing_status` flips from `CHARGED` to `CREDITED`, its postage is credited back to the vendor's remaining budget, and the cycle's `eligible_denominator` and `response_rate` are recomputed — an undeliverable case no longer counts toward the denominator.

### 3.5. Reconciliation, Adjudication, and Cycle Closure

When the fielding window has run its course, a `ProgramAdmin` closes fielding, moving the cycle from `FIELDING` to `RECONCILIATION`; the cycle must be `FIELDING` (`ERR_CYCLE_NOT_FIELDING`), and the logical clock's date must be on or after `fielding_end_date` (`ERR_FIELDING_WINDOW_NOT_CLOSED`). Every case still `IN_FIELD` transitions to `NONRESPONSE`.

Reopening is the cyclic loop back: from `RECONCILIATION` to `FIELDING`; the cycle must be `RECONCILIATION` (`ERR_CYCLE_NOT_RECONCILING`), and the logical clock's date must still be on or before `fielding_end_date` (`ERR_REOPEN_WINDOW_EXPIRED`). Every `NONRESPONSE` case turns back to `IN_FIELD`, and a cycle may swing between `FIELDING` and `RECONCILIATION` more than once within its window.

Reconciliation is where late responses are adjudicated. A `DataSteward` adjudicates a response in `PENDING_REVIEW` by supplying a `decision` of `INCLUDE` or `EXCLUDE`; the response must be `PENDING_REVIEW` (`ERR_RESPONSE_NOT_PENDING_REVIEW`) and the cycle must be `RECONCILIATION` (`ERR_CYCLE_NOT_RECONCILING`). A `decision` of `INCLUDE` moves the response to `INCLUDED` and increments the cycle's `completed_responses`; a `decision` of `EXCLUDE` moves it to `EXCLUDED`, leaving the counter untouched.

Duplicate or fraudulent responses are compensated by voiding. A `DataSteward` voids a response, supplying a `reason`, only while the response is `ACCEPTED` (`ERR_RESPONSE_NOT_VOIDABLE`) and only while the response's cycle is in `FIELDING` or `RECONCILIATION` (`ERR_CYCLE_LOCKED`). The response moves to `VOIDED`, and the cycle's `completed_responses` is recomputed downward. The intake-plus-void pair is exactly compensating: after both complete, `completed_responses` returns to its prior value with no drift, because only responses in `ACCEPTED` or `INCLUDED` ever count.

Whole cycles can be voided too. From any state except the terminal `PUBLISHED` or an already-`VOIDED` cycle (`ERR_INVALID_STATE`), a `ProgramAdmin` voids the cycle. The compensation is shared and total: every case of the cycle in `SAMPLED`, `IN_FIELD`, `NONRESPONSE`, or `UNDELIVERABLE` moves to `VOIDED`; each such case still `CHARGED` flips to `CREDITED` with its postage credited back to the vendor (a case already `CREDITED`, such as an undeliverable one, moves no budget); every response of the cycle in `ACCEPTED`, `PENDING_REVIEW`, or `INCLUDED` moves to `VOIDED`; and the cycle's counters are recomputed.

### 3.6. Scoring, Star Ratings, and Publication

Beginning scoring moves the cycle from `RECONCILIATION` to `SCORING`; the cycle must be `RECONCILIATION` (`ERR_CYCLE_NOT_RECONCILING`). It is blocked while any response of the cycle remains `PENDING_REVIEW` (`ERR_UNADJUDICATED_RESPONSES`) — every late response must be adjudicated first. Beginning scoring freezes the analytical snapshot: `scored_raw_composite_pcts` and `scored_adjusted_composite_pcts` hold the raw and mode-adjusted top-box percentages for the four composites keyed `nurse_comm`, `doctor_comm`, `cleanliness`, and `overall_rating`; `scored_unit_breakdown` and `scored_provider_breakdown` hold per-unit and per-provider entries carrying the `unit_id` or `provider_id`, that subject's `completed_responses`, and its `raw_pcts` and `adjusted_pcts`; and `scored_response_rate` and `scored_completed_responses` freeze the live counters.

The top-box mathematics work as follows. The input set is the cycle's responses in `ACCEPTED` or `INCLUDED`. For each composite, the **raw** view counts a response as top-box when its raw composite score equals 4. The **mode-adjusted** view first shifts each response's composite score by the coefficient of its `mode_used` — 0.0 for `MAIL`, negative 0.5 for `PHONE` — and counts it as top-box when the adjusted score is at least 3.75. A `PHONE` response with a raw 4 therefore adjusts to 3.5 and does not count, so whenever any top-box phone response exists, the adjusted percentages sit strictly below the raw ones. Each percentage is the count of top-box responses divided by the completed-responses count, multiplied by 100, rounded half-up to two decimal places; when the completed count is zero the percentage is null. The identical formula produces the program-level composites, the per-unit entries (grouping by the case's `unit_id`), and the per-provider entries (grouping by `provider_id`).

The cycle's response-rate machinery is live throughout. The `eligible_denominator` counts the cycle's cases in `IN_FIELD`, `RESPONDED`, or `NONRESPONSE` — excluding `SAMPLED`, `UNDELIVERABLE`, `EXCLUDED_POST_SAMPLE`, and `VOIDED` cases. The `completed_responses` counts the cycle's cases in `RESPONDED` whose non-voided response is `ACCEPTED` or `INCLUDED`. The `response_rate` is 100 times the completed count divided by the denominator, rounded half-up to two decimal places, and is null while the denominator is zero. Reading a cycle returns these live derived fields together with `sampled_count` and `publication_eligible` — the live preview of the publication gate, true exactly when `completed_responses` is at least 25 and `response_rate` is at least 10.0 — alongside the frozen snapshots once scoring has begun.

The star rating is computed live from the scored snapshot and is available once the cycle is `SCORING` or `PUBLISHED` (otherwise `ERR_CYCLE_NOT_SCORED`). A cycle whose `scored_completed_responses` is below 25 is not ratable: its `stars` are null, `rating_status` is `NOT_RATED`, and `capped` is false. Otherwise the rating reads the adjusted `overall_rating` percentage from the snapshot: at least 90.0 earns 5 stars, at least 80.0 earns 4, at least 70.0 earns 3, at least 60.0 earns 2, and anything below earns 1 — every boundary inclusive, so exactly 80.00 earns 4. A response-rate cap then applies: when `scored_response_rate` is below 10.0, the rating is capped at 3 stars (`stars` becomes the lesser of the earned rating and 3) and `capped` is true; at exactly 10.0 or above there is no cap. The rating payload carries `cycle_id`, `rating_status`, `stars`, `capped`, `adjusted_overall_topbox_pct`, `response_rate`, and `completed_responses`.

The same snapshot powers the attribution report, likewise available only while the cycle is `SCORING` or `PUBLISHED` (otherwise `ERR_CYCLE_NOT_SCORED`). The caller supplies exactly one of `unit_id` or `provider_id` to choose the reporting scope, and the report returns the `cycle_id`, the `scope`, the `subject_id`, and that subject's `completed_responses`, `raw_pcts`, and `adjusted_pcts` — the per-unit or per-provider entry frozen at begin-scoring.

Publication moves the cycle from `SCORING` to `PUBLISHED` — the cycle must be `SCORING` (`ERR_CYCLE_NOT_SCORED`) — and is the compliance gate of the program. The frozen snapshot must show `scored_completed_responses` of at least 25 and a `scored_response_rate` of at least 10.0, both thresholds inclusive; a cycle below either is rejected with `ERR_BELOW_PUBLICATION_THRESHOLD`. On publish, `published_star_rating` is pinned from the star rating of the stored snapshot and `published_at` is stamped from the logical clock.

Publication also fires the improvement cascade, in four hops. First the cycle pins its star rating. Then every improvement initiative whose `evaluation_cycle_id` is this cycle and whose status is `ACTIVE` moves to `UNDER_EVALUATION` and immediately branches: when the unit's published adjusted percentage for the initiative's domain in this cycle is at least the `target_score` — the comparison inclusive, so exactly meeting the target succeeds — the initiative lands in `TARGET_MET` and stamps `achieved_at` from the clock; otherwise it lands in `TARGET_MISSED`. For each initiative that lands `TARGET_MISSED`, every service-recovery ticket on the same `unit_id` and `domain` that is still `OPEN` escalates to `ESCALATED`. Finally, for each ticket escalated that way, the response it routes is marked `has_escalated_recovery` true. Both `PUBLISHED` and `VOIDED` are terminal for a cycle.

### 3.7. Value-Based Purchasing Projection and Mode-Transition Analysis

The VBP projection is a what-if model over the scored snapshot, run by a `ProgramAdmin` while the cycle is `SCORING` or `PUBLISHED` (otherwise `ERR_CYCLE_NOT_SCORED`); it persists nothing. The request may carry per-composite percentage overrides — `nurse_comm_pct`, `doctor_comm_pct`, `cleanliness_pct`, `overall_rating_pct` — and each composite's percentage is the override when supplied, else the snapshot's adjusted value. Each composite converts its percentage to points by subtracting the floor of 50.0, dividing by the span from the floor to the 95.0 benchmark, and multiplying by the 10 points available per composite; the result is rounded half-up to a whole number and clamped to the range 0 through 10. The rounding order is pinned: each composite's points are rounded before summing, and summing unrounded values is forbidden because the two orders disagree. The four integer line items sum to `total_points` out of a maximum of 40, and the `vbp_adjustment_pct` is that total divided by 40 and multiplied by the maximum adjustment of 2.0 percent, rounded half-up to two decimal places. The projection returns `cycle_id`, the per-composite `composite_points`, `total_points`, and `vbp_adjustment_pct`.

Mode-transition analysis compares the cycle in the path against another cycle supplied via `compare_to_cycle_id`; both must be `PUBLISHED` (`ERR_CYCLE_NOT_PUBLISHED`) and belong to the same program (`ERR_CROSS_PROGRAM_REFERENCE`). A cycle's mode share is the fraction of its counted responses — those in `ACCEPTED` or `INCLUDED` — that were collected in a given mode. The analysis returns `mail_share_delta` and `phone_share_delta`, each the path cycle's share minus the comparison cycle's share, rounded half-up to four decimal places; `raw_overall_delta` and `adjusted_overall_delta`, the differences between the two cycles' raw and adjusted overall-rating percentages, rounded half-up to two decimal places; and `mode_effect_delta`, built from each cycle's mode effect — its raw overall-rating percentage minus its adjusted one, the percentage points of top-box inflation attributable to mode mix — taking the path cycle's mode effect minus the comparison cycle's, rounded half-up to two decimal places. The response carries `cycle_id`, `compare_to_cycle_id`, and the five deltas.

### 3.8. Improvement Initiatives

An improvement initiative binds a unit, a domain, and two cycles. A `ProgramAdmin` creates one with `unit_id`, a `domain` (`NURSE_COMM`, `DOCTOR_COMM`, `CLEANLINESS`, or `OVERALL_RATING`), a `baseline_cycle_id`, an `evaluation_cycle_id`, and a `target_score` between 0 and 100 with at most two decimal places. The `program_id` is denormalized from the unit's program, and the referenced cycles must belong to that same program (`ERR_CROSS_PROGRAM_REFERENCE`); the evaluation-window rules described at activation — index ordering and the half-open overlap check — are enforced whenever an initiative is created, activated, or replanned. A new initiative is `DRAFT` with `baseline_score`, both progress fields, and `achieved_at` all null.

Activation moves the initiative from `DRAFT` to `ACTIVE` (from any other status, `ERR_INVALID_STATE`) under four guards. The baseline cycle must be `PUBLISHED` (`ERR_BASELINE_CYCLE_NOT_PUBLISHED`). The evaluation cycle must belong to the same program as the unit (`ERR_CROSS_PROGRAM_REFERENCE`). The evaluation cycle must not be `VOIDED` and its `cycle_index` must be strictly greater than the baseline cycle's (`ERR_INVALID_EVALUATION_CYCLE`). And the half-open window from the baseline index (exclusive) through the evaluation index (inclusive) must not intersect the corresponding window of any other initiative on the same unit and domain whose status is `ACTIVE`, `UNDER_EVALUATION`, or `TARGET_MISSED` (`ERR_INITIATIVE_WINDOW_OVERLAP`); mere adjacency, where one initiative's evaluation index equals another's baseline index, is permitted. Activation pins the `baseline_score`: the unit's published adjusted top-box percentage for the domain, read from the baseline cycle's `scored_unit_breakdown` and frozen for the life of the initiative.

Progress is computed live on read and populates once the evaluation cycle is `PUBLISHED`. Both variants measure the unit's adjusted percentage for the domain in the evaluation cycle's unit breakdown — call it the current value. The **pinned** variant, `progress_pinned`, is the current value minus the frozen `baseline_score`, rounded half-up to two decimal places; it is null until the evaluation cycle publishes. The **rolling** variant, `progress_rolling`, measures against the trailing average: take the up-to-two most recent `PUBLISHED` cycles of the same program whose `cycle_index` is strictly below the evaluation cycle's, ordered by `cycle_index` descending with `created_at` descending as tie-break; the rolling baseline is the average of the unit's adjusted percentage for the domain across those cycles, rounded half-up to two decimal places, and is null when no such cycle exists. `progress_rolling` is the current value minus the rolling baseline, rounded half-up to two decimal places — the baseline is rounded before the subtraction — and is null whenever the rolling baseline is null or the evaluation cycle has not published.

Evaluation happens at the publish checkpoint of the evaluation cycle, as told in §3.6. When the unit is absent from the cycle's `scored_unit_breakdown`, or its breakdown entry shows zero completed responses, the current value is treated as 0.0. Meeting or exceeding `target_score` lands `TARGET_MET`; falling short lands `TARGET_MISSED` and escalates the unit's open tickets in that domain.

A missed target is not the end. A `ProgramAdmin` replans an initiative in `TARGET_MISSED` back to `ACTIVE` (from any other status, `ERR_INVALID_STATE`), supplying a replacement `evaluation_cycle_id` and `target_score`; the new evaluation cycle re-runs the same guards — same program as the unit (`ERR_CROSS_PROGRAM_REFERENCE`), not `VOIDED` with a `cycle_index` strictly above the baseline's (`ERR_INVALID_EVALUATION_CYCLE`), and the half-open window overlap check against `ACTIVE`, `UNDER_EVALUATION`, and `TARGET_MISSED` peers (`ERR_INITIATIVE_WINDOW_OVERLAP`). Replanning resets `progress_pinned` and `progress_rolling` to null and leaves the pinned `baseline_score` unchanged. An initiative may also be cancelled from `DRAFT`, `ACTIVE`, or `TARGET_MISSED` to `CANCELLED` (from any other status, `ERR_INVALID_STATE`).

### 3.9. Comment Routing and Service Recovery

When a response's comment demands follow-up, a `UnitManager` routes it into a service-recovery ticket, supplying `unit_id`, `response_id`, the `domain` the comment concerns, and a `priority` of `LOW`, `MEDIUM`, or `HIGH`. Routing enforces the chain of custody: the manager's `X-User-ID` must equal the ticket's `unit_id` (`ERR_UNIT_ACCESS_DENIED`); the response's attributed unit — the `unit_id` of its sample case — must equal the ticket's `unit_id` (`ERR_UNIT_RESPONSE_MISMATCH`); the response must be in `ACCEPTED` or `INCLUDED` (`ERR_RESPONSE_NOT_FINAL`); and the response must carry a non-empty `comment_text`, because there is nothing to route without one (`ERR_NO_COMMENT_TO_ROUTE`). The ticket starts `OPEN`, its `program_id` is denormalized from the unit's program, and `created_at` comes from the logical clock.

Acknowledgement is the unit's first commitment. A `UnitManager` acknowledges a ticket in `OPEN` or `ESCALATED` (otherwise `ERR_TICKET_NOT_ACKNOWLEDGEABLE`), again only on their own unit's tickets (`ERR_UNIT_ACCESS_DENIED`). Acknowledgement stamps `acknowledged_at` from the clock and computes `acknowledged_within_sla`: true exactly when the elapsed time from `created_at` to `acknowledged_at` is at most 48 hours. The boundary is inclusive — exactly 48 hours, 0 minutes, 0 seconds is within SLA; one second beyond is not. Until acknowledgement, `acknowledged_within_sla` is null.

Resolution closes the loop: a `UnitManager` resolves a ticket in `ACKNOWLEDGED` (otherwise `ERR_TICKET_NOT_RESOLVABLE`, and again only on their own unit's tickets), supplying a `resolution_note` that is stored on the ticket. `RESOLVED` is terminal.

Escalation arrives from the improvement side, not from the queue. When publication of an evaluation cycle lands an initiative in `TARGET_MISSED`, every `OPEN` ticket on the same unit and domain moves to `ESCALATED`, and each escalated ticket's linked response is marked `has_escalated_recovery` true. An escalated ticket is acknowledged and resolved through the same path as any other.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger a state transition return `200 OK`. All resource endpoints are mounted under `/api`; the logical-clock control is mounted at the server root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/survey-programs` | Create a survey program | ProgramAdmin |
| GET | `/api/survey-programs/{programId}` | Get a program (includes `version` for OCC) | Any |
| POST | `/api/vendors` | Register a vendor; supersedes the program's ACTIVE vendor (OCC-guarded) | ProgramAdmin |
| GET | `/api/vendors` | List vendors (filters: `program_id`, `status`) | Any |
| GET | `/api/vendors/{vendorId}` | Get a vendor (budget and remaining) | Any |
| POST | `/api/vendors/{vendorId}/suspend` | Suspend an ACTIVE vendor | ProgramAdmin |
| POST | `/api/units` | Create a care unit | ProgramAdmin |
| GET | `/api/units` | List units (filter: `program_id`) | Any |
| GET | `/api/units/{unitId}` | Get a unit | Any |
| POST | `/api/providers` | Create a provider | ProgramAdmin |
| GET | `/api/providers` | List providers (filter: `program_id`) | Any |
| GET | `/api/providers/{providerId}` | Get a provider | Any |
| POST | `/api/discharges` | Intake one discharge | DataSteward |
| POST | `/api/discharges/import` | Bulk discharge feed with auto-evaluation | DataSteward |
| GET | `/api/discharges` | List discharges (filters: `program_id`, `unit_id`, `provider_id`, `status`) | Any |
| GET | `/api/discharges/{dischargeId}` | Get a discharge (status and exclusion reasons) | Any |
| POST | `/api/discharges/{dischargeId}/evaluate` | Re-run exclusion rules with optional corrected fields | DataSteward |
| POST | `/api/cycles` | Create a survey cycle | ProgramAdmin |
| GET | `/api/cycles` | List cycles (filters: `program_id`, `status`) | Any |
| GET | `/api/cycles/{cycleId}` | Get a cycle with live derived fields and snapshots | Any |
| POST | `/api/cycles/{cycleId}/open-sampling` | DRAFT to SAMPLING_OPEN | ProgramAdmin |
| POST | `/api/cycles/{cycleId}/start-fielding` | SAMPLING_OPEN to FIELDING; dispatches SAMPLED cases | ProgramAdmin |
| POST | `/api/cycles/{cycleId}/close-fielding` | FIELDING to RECONCILIATION | ProgramAdmin |
| POST | `/api/cycles/{cycleId}/reopen-fielding` | RECONCILIATION back to FIELDING | ProgramAdmin |
| POST | `/api/cycles/{cycleId}/begin-scoring` | RECONCILIATION to SCORING; freezes the snapshot | ProgramAdmin |
| POST | `/api/cycles/{cycleId}/publish` | SCORING to PUBLISHED; fires the initiative cascade | ProgramAdmin |
| POST | `/api/cycles/{cycleId}/void` | Void a non-terminal cycle with compensating credits | ProgramAdmin |
| GET | `/api/cycles/{cycleId}/star-rating` | Computed star rating from the scored snapshot | Any |
| GET | `/api/cycles/{cycleId}/attribution-report` | Unit- or provider-level report (exactly one of `unit_id` or `provider_id`) | Any |
| POST | `/api/cycles/{cycleId}/vbp-projection` | What-if VBP impact model over the scored snapshot | ProgramAdmin |
| GET | `/api/cycles/{cycleId}/mode-transition-analysis` | Mode-mix comparison against another PUBLISHED cycle | Any |
| POST | `/api/sample-cases` | Sample one discharge into a cycle | DataSteward |
| POST | `/api/sample-cases/import` | Bulk sampling from a `discharge_ids` list | DataSteward |
| GET | `/api/sample-cases` | List sample cases (filters: `cycle_id`, `discharge_id`, `vendor_id`, `unit_id`, `provider_id`, `status`) | Any |
| GET | `/api/sample-cases/{caseId}` | Get a sample case | Any |
| GET | `/api/sample-cases/{caseId}/responses` | List the case's responses | Any |
| POST | `/api/sample-cases/{caseId}/mark-undeliverable` | Mark an IN_FIELD case undeliverable with budget credit | VendorOperator |
| POST | `/api/responses` | Survey response intake | VendorOperator |
| POST | `/api/responses/import` | Bulk response intake from a `case_ids` list | VendorOperator |
| GET | `/api/responses` | List responses (filters: `case_id`, `cycle_id`, `status`, `mode_used`) | Any |
| GET | `/api/responses/{responseId}` | Get a response | Any |
| POST | `/api/responses/{responseId}/adjudicate` | Adjudicate a late response INCLUDE or EXCLUDE | DataSteward |
| POST | `/api/responses/{responseId}/void` | Void an ACCEPTED response | DataSteward |
| POST | `/api/initiatives` | Create an improvement initiative | ProgramAdmin |
| GET | `/api/initiatives` | List initiatives (filters: `unit_id`, `program_id`, `baseline_cycle_id`, `evaluation_cycle_id`, `status`) | Any |
| GET | `/api/initiatives/{initiativeId}` | Get an initiative with progress fields | Any |
| POST | `/api/initiatives/{initiativeId}/activate` | DRAFT to ACTIVE; pins the baseline score | ProgramAdmin |
| POST | `/api/initiatives/{initiativeId}/replan` | TARGET_MISSED back to ACTIVE with a new window | ProgramAdmin |
| POST | `/api/initiatives/{initiativeId}/cancel` | Cancel an initiative | ProgramAdmin |
| POST | `/api/service-recovery-tickets` | Route a response's comment into a ticket | UnitManager |
| GET | `/api/service-recovery-tickets` | List tickets (filters: `unit_id`, `program_id`, `response_id`, `status`) | Any |
| GET | `/api/service-recovery-tickets/{ticketId}` | Get a ticket (including SLA outcome) | Any |
| POST | `/api/service-recovery-tickets/{ticketId}/acknowledge` | Acknowledge an OPEN or ESCALATED ticket | UnitManager |
| POST | `/api/service-recovery-tickets/{ticketId}/resolve` | Resolve an ACKNOWLEDGED ticket | UnitManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VENDOR_CASE_MISMATCH` | 403 Forbidden |
| `ERR_UNIT_ACCESS_DENIED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_NOT_SAMPLING_OPEN` | 409 Conflict |
| `ERR_CYCLE_NOT_FIELDING` | 409 Conflict |
| `ERR_CYCLE_NOT_RECONCILING` | 409 Conflict |
| `ERR_CYCLE_NOT_SCORED` | 409 Conflict |
| `ERR_CYCLE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_CYCLE_LOCKED` | 409 Conflict |
| `ERR_NO_ACTIVE_VENDOR` | 409 Conflict |
| `ERR_NO_CASES_SAMPLED` | 409 Conflict |
| `ERR_UNADJUDICATED_RESPONSES` | 409 Conflict |
| `ERR_CASE_NOT_IN_FIELD` | 409 Conflict |
| `ERR_RESPONSE_NOT_PENDING_REVIEW` | 409 Conflict |
| `ERR_RESPONSE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_RESPONSE_NOT_FINAL` | 409 Conflict |
| `ERR_DISCHARGE_LOCKED_BY_SAMPLE` | 409 Conflict |
| `ERR_BASELINE_CYCLE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_TICKET_NOT_ACKNOWLEDGEABLE` | 409 Conflict |
| `ERR_TICKET_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_DISCHARGE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CROSS_PROGRAM_REFERENCE` | 400 Bad Request |
| `ERR_UNIT_RESPONSE_MISMATCH` | 400 Bad Request |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DISCHARGE_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_FIELDING_WINDOW_NOT_CLOSED` | 409 Conflict |
| `ERR_REOPEN_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_INVALID_EVALUATION_CYCLE` | 422 Unprocessable Entity |
| `ERR_INITIATIVE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_UNIT_CODE` | 409 Conflict |
| `ERR_DUPLICATE_CYCLE_INDEX` | 409 Conflict |
| `ERR_DUPLICATE_NPI` | 409 Conflict |
| `ERR_DISCHARGE_ALREADY_SAMPLED` | 409 Conflict |
| `ERR_SAMPLE_TARGET_REACHED` | 422 Unprocessable Entity |
| `ERR_MODE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_RESPONSE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_NO_COMMENT_TO_ROUTE` | 422 Unprocessable Entity |
| `ERR_BELOW_PUBLICATION_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_VENDOR_BUDGET_EXCEEDED` | 402 Payment Required |
