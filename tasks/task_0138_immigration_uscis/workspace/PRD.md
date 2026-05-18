# Immigration USCIS API — Product Requirements Document

## 1. Introduction

Family-based immigration adjudication is a workflow in which a small set of forms — the I-130 Petition for Alien Relative, the I-485 Adjustment of Status, the I-765 Employment Authorization, and the I-131 Advance Parole — move through a sequence of operational milestones (filing, biometrics capture, evidentiary requests, AOS interview, decision) while also being subject to an external visa-availability signal published monthly by the Department of State. Today, petitioners and beneficiaries have little programmatic insight into where their filings stand, officers stitch together status from disconnected appointment and evidence subsystems, and supervisors lack a deterministic record of how a Priority Date became "current" on the day it did.

This document specifies an API that consolidates the entire family-immigration case journey behind a single coherent resource model. The system mints USCIS-style Receipt Numbers, schedules and tracks biometrics at Application Support Centers, issues and resolves Requests for Evidence (RFEs), maintains monthly Visa Bulletin snapshots across both the Final Action and Dates for Filing charts, and schedules Adjustment of Status interviews. Adjudication outcomes recorded against an I-130 must cascade deterministically to any dependent I-485 filings, and Priority-Date currency must be computable both on demand and as bulletins are republished.

The design favours determinism over convenience. Receipt Numbers must be reproducible from a pinned input order, Priority-Date currency under a given chart must yield a single answer, and every state change must be observable through an immutable audit feed.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, an opaque or entity-backed actor identifier, and `X-User-Role`, the actor's role string. A request that omits either header — or supplies an empty value — is rejected with `ERR_AUTH_MISSING_HEADERS` (HTTP 401). A request whose `X-User-Role` value does not match one of the four defined roles is rejected with `ERR_AUTH_UNKNOWN_ROLE` (HTTP 401). A request whose role is known but is not permitted to perform the requested operation, or to act on the targeted resource, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are `Petitioner`, `Beneficiary`, `Officer`, and `Supervisor`, spelled exactly as shown. Each role is one of two identity flavours:

- When `X-User-Role` is `Petitioner`, `X-User-ID` is the `id` of the acting `Petitioner`; ownership checks on any resource that references a `Petitioner` compare the resource's `petitioner_id` field to `X-User-ID`. Petitioners may read and act only on cases whose `petitioner_id` matches their own `X-User-ID`.
- When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`; ownership checks compare the targeted case's `beneficiary_id` (or the targeted beneficiary record's own `id`) to `X-User-ID`. A `Beneficiary` may fetch their own beneficiary record and read or respond on cases where they are the beneficiary.
- When `X-User-Role` is `Officer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_role`'s associated user reference on a `CaseEvent`) but does not compare it to any entity's `id`. Officers may operate on any case.
- When `X-User-Role` is `Supervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded only for audit. A `Supervisor` may perform every operation an `Officer` may perform, and additionally configure case types, publish visa bulletins, set the chart in effect, and advance the test clock.

The role check is the third validation gate, evaluated after header presence and role recognition; see §2.4 for full ordering.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100. The default `offset` is 0 and the minimum is 0. A request whose `limit` falls outside the inclusive range 1 to 100, or whose `offset` is negative, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422). List endpoints sort results by `created_at` in ascending order. The `meta` envelope on a list response includes the echoed `limit`, the echoed `offset`, a `total_count` reflecting the total matching rows, and a `has_more` boolean indicating whether more rows are reachable past the current page.

### 2.4. Validation Order and Error Precedence

Validation is layered, not parallel. The system evaluates checks in the following fixed order, returning the first failure rather than aggregating:

1. **Header presence** — missing or empty `X-User-ID` or `X-User-Role` yields `ERR_AUTH_MISSING_HEADERS`.
2. **Role recognition** — an unknown `X-User-Role` yields `ERR_AUTH_UNKNOWN_ROLE`.
3. **Role authorization** — a known role lacking permission for the operation or resource yields `ERR_FORBIDDEN`.
4. **Path-resource existence** — every path segment is resolved left to right (`case_id`, then nested `biometrics_id`, `rfe_id`, `interview_id`, `beneficiary_id`, or `petitioner_id` as applicable); any unresolved segment yields `ERR_NOT_FOUND`.
5. **Body-reference existence** — foreign-key identifiers carried in the request body (such as `petitioner_id`, `beneficiary_id`, `linked_i130_case_id`) must resolve, or the request is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` on case creation and filing.
6. **State precondition** — the target resource must be in a state from which the requested transition is permitted, otherwise `ERR_INVALID_STATE` is returned.
7. **Business-safety, business-referential, business-temporal, and business-constraint rules** — domain-specific guards described in §3 fire after the existence and state gates. Within this band the priority order matters when two business rules could fire on the same request: an I-485 filing missing an approved I-130 link is screened (`ERR_I485_MISSING_APPROVED_I130`) before the priority-date currency check (`ERR_PRIORITY_DATE_NOT_CURRENT`) which precedes the OUTSTANDING-RFE uniqueness check (`ERR_RFE_ALREADY_OUTSTANDING`), the SCHEDULED-biometrics uniqueness check (`ERR_BIOMETRICS_ALREADY_SCHEDULED`), the biometrics-too-soon check (`ERR_BIOMETRICS_TOO_SOON`), the interview-too-soon check (`ERR_INTERVIEW_TOO_SOON`), the RFE-deadline-passed check (`ERR_RFE_DEADLINE_PASSED`), the biometrics reschedule-count cap (`ERR_BIOMETRICS_RESCHEDULE_LIMIT`), the biometrics reschedule-too-late guard (`ERR_BIOMETRICS_RESCHEDULE_TOO_LATE`), the interview-applicability guard (`ERR_INTERVIEW_NOT_APPLICABLE`), the optimistic-concurrency check (`ERR_VERSION_CONFLICT`), and finally the receipt-number uniqueness check (`ERR_RECEIPT_NUMBER_COLLISION`).
8. **Pagination shape** — list endpoints check `limit` and `offset` ranges, returning `ERR_INVALID_PAGINATION`.
9. **Body shape** — required fields, enum membership, and ISO-8601 date well-formedness are verified last; any violation yields `ERR_VALIDATION`.

### 2.5. Common Resource Properties

Every persisted entity carries a server-minted `id` formatted as a UUID with no type prefix and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most entities additionally carry an `updated_at` timestamp with the same format that refreshes on every mutation, and a monotonic integer `version` that increments by one on every mutation. The two entities that do not carry `updated_at` or `version` are `CaseTypeConfig`, `VisaBulletin`, and `CaseEvent`: a `CaseTypeConfig` row only carries `id` and `created_at`, a `VisaBulletin` row only carries `id`, `created_at`, and its own `published_at` field (set by the server when the row is published), and a `CaseEvent` carries only `id`, `created_at`, and its own `occurred_at`. These three entities are immutable once written, except for the `CaseTypeConfig` upsert flow described in §3.

### 2.6. Optimistic Concurrency Control

Any client mutating an entity via a `PATCH` endpoint may include a `version` field in the request body matching the entity's current `version`. When the supplied `version` does not match the persisted `version`, the mutation is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). Omitting the `version` field skips the check and lets the mutation proceed. Successful mutation increments `version` by exactly one and refreshes `updated_at` to the current server time. The same optimistic-concurrency mechanism governs the racing-decision scenario in §3: when an officer's approve action and the system's RFE-timeout auto-denial both target the same case, the first writer wins on `Case.status`, and the loser observes the case already in its new terminal state and is rejected with `ERR_INVALID_STATE`. Two simultaneous filings that race to mint the same `receipt_number` on the same `receipt_prefix` are serialized through a monotonic per-prefix sequence; the loser is rejected with `ERR_RECEIPT_NUMBER_COLLISION` and retries to obtain the next sequence value.

### 2.7. Receipt Numbering and Deterministic Identifiers

Receipt Numbers are exactly 13 characters long and globally unique across the system. They are minted at the moment a case enters the filed state and never reissued. The character layout is fixed and the minting order is pinned: first, the three-letter prefix is read from the matching `CaseTypeConfig.receipt_prefix`; then the last two digits of the current calendar year are taken from the wall clock as a zero-padded two-digit string; then the current day of the federal fiscal year — counting from October 1 of the year whose start of fiscal year contains today (October 1 of the current calendar year if today is in October, November, or December, and October 1 of the prior calendar year otherwise) — is taken as a zero-padded three-digit string between 001 and 366; then a per-prefix, per-fiscal-year monotonic integer sequence is consumed atomically and rendered as a zero-padded five-digit string; finally these four segments are concatenated in that order to produce the Receipt Number. Three-letter prefix, two-digit year, three-digit day-of-fiscal-year, and five-digit sequence sum to thirteen characters. No rounding applies — all arithmetic is integer and all formatting is zero-padded string concatenation. The valid `receipt_prefix` values are `MSC`, `EAC`, `WAC`, `NBC`, `LIN`, `SRC`, `IOE`, and `YSC`. Concurrent filings on the same prefix in the same fiscal year are serialized through the monotonic sequence: at most one filer wins each integer, and the loser retries to receive the next.

### 2.8. Numeric Precision and Rounding

Two numeric outputs require pinned precision and rounding. The case completeness score uses two decimal places at the per-factor level and zero decimal places at the final integer level, both with the half-up rounding convention. Specifically, each factor's weighted product (its raw 0-to-1 score multiplied by its weight) is rounded to two decimal places half-up first, the five rounded per-factor scores are summed, the sum is multiplied by 100, and the result is rounded to a whole number half-up. The score is then clamped into the inclusive 0-to-100 integer range. The RFE response deadline is stored as an ISO 8601 timestamp to millisecond precision; comparisons against it use strict greater-than semantics, so the exact instant equal to `deadline_at` is still in-window and only a strictly later instant marks the RFE as past due.

### 2.9. Priority Date Currency and the Visa Bulletin

USCIS publishes two charts each month: the Final Action chart and the Dates for Filing chart. The system holds bulletin rows for both, and a server-managed `chart_in_effect` setting (defaulting to `FINAL_ACTION`) determines which chart governs priority-date currency for I-485 adjudication. Switching the chart in effect does not retroactively rewrite any case's stored status — it changes the answer the next time `priority_date_currency` is invoked.

Determining whether a case's `priority_date` is current proceeds deterministically. First, the system pins the latest bulletin month, defined as the lexically largest `bulletin_month` value (in `YYYY-MM` form) across all chart types; ties are broken by the most recent `published_at`. Second, among the rows of the chart in effect for that month, it selects the row whose `preference_category` equals the beneficiary's `preference_category` and whose `country` is either the beneficiary's `country_of_chargeability` or the literal `ROW`; when both a country-specific row and a `ROW` row are present, the country-specific row wins. Third, the row's `cutoff_date` is interpreted: a `cutoff_date` of `CURRENT` means the priority date is current and the case's `priority_date_status` is `CURRENT`; a `cutoff_date` of `UNAVAILABLE` means no dates are current and the status is `NOT_CURRENT`; otherwise the `cutoff_date` is a real date and the case's `priority_date` is current when it falls strictly before the cutoff date, and not current when it is equal to or later than the cutoff date — the cutoff date itself is not yet current. Finally, retrogression detection compares the just-computed status against the previously stored `priority_date_status` on the same case: if the previous status was `CURRENT` and the newly computed status is `NOT_CURRENT`, the status is recorded as `RETROGRESSED` instead. When no row matches the (chart, category, country) selection at all, the status is `NOT_CURRENT`. All comparisons are date-only with no time component, and the comparison operator is strict less-than.

A case for which priority-date currency does not apply — because its `case_type` is `I-130`, `I-765`, or `I-131`, or because the beneficiary's `preference_category` is `IR` (immediate relative, exempt from numerical limits) — carries `priority_date_status` permanently set to `NOT_APPLICABLE`.

### 2.10. Audit Trail

Every meaningful state mutation emits a `CaseEvent` row under the affected case. The event records its `event_type` (one of `STATUS_CHANGED`, `BIOMETRICS_SCHEDULED`, `BIOMETRICS_COMPLETED`, `RFE_ISSUED`, `RFE_RESPONDED`, `INTERVIEW_SCHEDULED`, `BULLETIN_REFRESHED`, `PRIORITY_DATE_RECOMPUTED`, `DECISION_RECORDED`), the `from_value` and `to_value` strings (for example the prior and new `status`, or the prior and new `priority_date_status`), the `actor_role` string copied from the originating request's `X-User-Role` (or the literal `"system"` for sweeps driven by clock advance), and the `occurred_at` UTC timestamp of the event. Audit rows are never updated or deleted.

## 3. Business Logic & Workflows

### 3.1. Petitioner and Beneficiary Profiles

The first interaction with the system is the creation of a `Petitioner` profile. The petitioner supplies a `full_name` between 1 and 120 characters, a `date_of_birth` expressed as an ISO 8601 calendar date in `YYYY-MM-DD` form that must fall at least fourteen years before today, a `country_of_citizenship` written as a three-letter uppercase ISO 3166-1 alpha-3 country code, and an `email` address conforming to RFC 5322 for officer correspondence. An optional `a_number` may be supplied for petitioners who already hold an Alien Registration Number; when present it must match the pattern of a capital A followed by exactly nine digits, and when absent the value defaults to null.

Under that petitioner, the sponsor registers one or more `Beneficiary` profiles. A beneficiary record carries its own `full_name` (also between 1 and 120 characters), `date_of_birth` as an ISO 8601 date, `country_of_chargeability` as a three-letter uppercase ISO 3166-1 alpha-3 code that the visa-bulletin lookup will consult, a `preference_category` selected from `F1`, `F2A`, `F2B`, `F3`, `F4`, or `IR` (where `IR` marks an immediate relative exempt from numerical limits), and a `relationship_to_petitioner` chosen from `SPOUSE`, `CHILD`, `PARENT`, `SIBLING`, or `FIANCE`. The `petitioner_id` linking the beneficiary back to the sponsor is established by the path of the creation call rather than carried in the body. Both `Petitioner` and `Beneficiary` records carry the common `id`, `created_at`, `updated_at`, and `version` fields described in §2.5.

A `Petitioner` may create only their own petitioner record (their `X-User-ID` becomes its `id`), only beneficiaries under that own petitioner, and only cases referencing that own petitioner; an attempt to act on another petitioner's resources is rejected with `ERR_FORBIDDEN`. A `Beneficiary` may fetch only their own beneficiary record.

### 3.2. Case Creation and Filing

A new case is created by a `Petitioner` or `Officer` in a payload identifying the `petitioner_id`, the `beneficiary_id`, and the `case_type` chosen from `I-130`, `I-485`, `I-765`, or `I-131`. The optional `linked_i130_case_id` is supplied only when the new case is an I-485 whose priority date will be inherited from a previously approved I-130. The new case is born in `DRAFT` status, with `priority_date` null, `priority_date_status` set to `NOT_APPLICABLE`, `rfe_deadline` null, `decision_at` null, and `denial_reason` null. If any of the body-referenced foreign keys (`petitioner_id`, `beneficiary_id`, `linked_i130_case_id`) cannot be resolved at creation time, the request is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND`.

A case is filed by its acting `Petitioner` to move from `DRAFT` to `FILED`. Filing requires that `petitioner_id`, `beneficiary_id`, and `case_type` all be set on the case. For an I-485 filing where the beneficiary's `preference_category` is anything other than `IR`, the case's `linked_i130_case_id` must point to an existing I-130 whose own `status` is `APPROVED`; otherwise the filing is rejected with `ERR_I485_MISSING_APPROVED_I130`. Filing pins the `filing_date` to the current UTC instant, mints the `receipt_number` according to the deterministic 13-character algorithm in §2.7 (any race that produces a collision is rejected on the loser with `ERR_RECEIPT_NUMBER_COLLISION`, which the loser is expected to retry), and pins `priority_date` according to case type: an I-130 filing sets `priority_date` to today's UTC date (the date portion of `filing_date`), an I-485 filing whose `linked_i130_case_id` is set copies that linked I-130's `priority_date` onto this case, and I-765 and I-131 filings leave `priority_date` null. When the matching `CaseTypeConfig.requires_priority_date_current` is true — which is the case for I-485 outside the IR category — the case's `priority_date_status` is recomputed against the latest visa bulletin (the first cascade hop). A `STATUS_CHANGED` `CaseEvent` records the `DRAFT` to `FILED` transition.

### 3.3. Case-Type Configuration

Each `case_type` is governed by a `CaseTypeConfig` row maintained by `Supervisor`s. The configuration declares `requires_biometrics` (whether biometrics capture must complete before approval), `requires_interview` (whether an AOS interview must complete before approval), `rfe_response_window_days` (a positive integer, typically 87, naming how many days an RFE recipient has to respond before automatic denial), `requires_priority_date_current` (whether Visa Bulletin currency gates approval — true for I-485 outside the IR category), and `receipt_prefix` (the three-letter service-center prefix used to mint Receipt Numbers, drawn from the prefix set listed in §2.7). The upsert is idempotent on `case_type`: re-publishing a configuration with the same `case_type` replaces the prior row.

### 3.4. The Biometrics Lifecycle

Following the filed state, when the governing `CaseTypeConfig.requires_biometrics` is true, an `Officer` schedules a biometrics appointment. The officer supplies `scheduled_at` as a UTC datetime and `location_code` as a 4-to-6-character uppercase alphanumeric Application Support Center identifier. The `scheduled_at` value must be at least seven days from the present moment; an earlier value is rejected with `ERR_BIOMETRICS_TOO_SOON`. Only one `SCHEDULED` `Biometrics` row may exist per case at a time — an attempt to schedule a second concurrent appointment is rejected with `ERR_BIOMETRICS_ALREADY_SCHEDULED`. Successful scheduling creates a fresh `Biometrics` row with `status` initialized to `SCHEDULED`, `reschedule_count` initialized to 0, and `completed_at` null, and advances the parent case's `status` to `BIOMETRICS_SCHEDULED`.

The biometrics appointment can be completed, marked no-show, or rescheduled. Marking the appointment completed requires that its current `status` be `SCHEDULED` and that the current time be at or after the recorded `scheduled_at`. The completion sets `completed_at` to the present instant, updates the appointment's `status` to `COMPLETED`, and — when the parent case is still in `BIOMETRICS_SCHEDULED` — advances the case to `BIOMETRICS_COMPLETED`. Marking the appointment as `NO_SHOW` requires that the current time be more than 24 hours past the scheduled time; the parent case remains in `BIOMETRICS_SCHEDULED` so the officer can reschedule.

Rescheduling has three preconditions in addition to the appointment's `SCHEDULED` state. The new appointment's `new_scheduled_at` must again be at least seven days into the future (`ERR_BIOMETRICS_TOO_SOON`); the request must arrive no later than 24 hours before the existing appointment's `scheduled_at` (`ERR_BIOMETRICS_RESCHEDULE_TOO_LATE`); and the current `reschedule_count` on the chain must be strictly less than 3, so the fourth reschedule attempt on the same chain is rejected with `ERR_BIOMETRICS_RESCHEDULE_LIMIT`. A successful reschedule from a still-`SCHEDULED` row marks the old row's `status` as `RESCHEDULED` and creates a new `Biometrics` row inheriting the case's `case_id` and the supplied `location_code`, in initial `status` `SCHEDULED`, with `reschedule_count` set to the prior row's `reschedule_count` plus one. A reschedule originating from a `NO_SHOW` row follows the same count-increment rule and leaves the prior `NO_SHOW` row untouched for audit, while the newly created row enters `SCHEDULED`; the same maximum-count cap applies.

### 3.5. Requests for Evidence

When the officer requires additional documentation, an RFE is issued against the case. The officer supplies the `reason_code` (one of `MISSING_DOC`, `IDENTITY_DOC`, `FINANCIAL_PROOF`, `MEDICAL_EXAM`, or `TRANSLATION`) and `officer_notes` between 1 and 2000 characters. Issuing an RFE requires that no other RFE on the case currently sit in `OUTSTANDING` status; a second concurrent issue attempt is rejected with `ERR_RFE_ALREADY_OUTSTANDING`, and when two officers attempt to issue an RFE on the same case at the same instant the first writer wins and the second receives `ERR_RFE_ALREADY_OUTSTANDING` referencing the existing RFE's `id`. When the governing `CaseTypeConfig.requires_biometrics` is true the case must already have completed biometrics before an RFE can issue (so the parent transitions are `BIOMETRICS_COMPLETED → RFE_ISSUED`); when biometrics is not required the RFE may issue directly from `FILED` (so the parent transitions are `FILED → RFE_ISSUED`). An RFE may also be issued from `INTERVIEW_SCHEDULED` if new gaps surface during interview preparation.

The RFE row is created with `issued_at` pinned to the present instant. Its `deadline_at` is set to `issued_at` plus the matching `CaseTypeConfig.rfe_response_window_days` converted to seconds (each day is 86,400 seconds; the default window across all four form types is 87 days). The same instant is mirrored onto the parent case's `rfe_deadline` field, so a reader of the case knows when evidence is due without joining to the RFE row. The RFE is created in `status` `OUTSTANDING`, with `response_received_at` null. The parent case transitions to `RFE_ISSUED`, and an `RFE_ISSUED` audit event is emitted.

The beneficiary (or the petitioner acting for the beneficiary) responds to an RFE. The response is accepted only while the RFE's `status` is still `OUTSTANDING` and the current time is at or before `deadline_at`. A response received strictly after `deadline_at` is rejected with `ERR_RFE_DEADLINE_PASSED`. Accepting a response sets the RFE's `status` to `RESPONDED`, pins `response_received_at` to the present instant, clears the case's `rfe_deadline` back to null, transitions the parent case from `RFE_ISSUED` to `RFE_RESPONDED`, and emits an `RFE_RESPONDED` audit event. A race between a beneficiary response and a clock-driven expiry is resolved first-writer-wins on `RFE.status`: if expiry won, the response is rejected with `ERR_RFE_DEADLINE_PASSED` and the loser sees the RFE already in `EXPIRED`.

If the deadline passes without a response, automatic denial fires through the test clock (see §3.10). The RFE's `status` becomes `EXPIRED`, the parent case's `status` becomes `DENIED`, the case's `denial_reason` is set to `RFE_TIMEOUT`, and the case's `decision_at` is pinned to the moment of expiry. The case's `priority_date` and `priority_date_status` are left unchanged because the case is now terminal. For an expired RFE that lived on an I-130, no priority-date inheritance change happens to any dependent I-485 because the I-130 was not approved.

### 3.6. The AOS Interview Lifecycle

The Adjustment of Status interview is only valid for I-485 cases — `CaseTypeConfig.requires_interview` is true only when `case_type` is `I-485`. Scheduling an interview against any other case type is rejected with `ERR_INTERVIEW_NOT_APPLICABLE`. The officer supplies a `scheduled_at` UTC datetime and a `field_office_code` of 3-to-5 uppercase letters identifying the field office. The `scheduled_at` must be at least 14 days into the future, or the request is rejected with `ERR_INTERVIEW_TOO_SOON`. The interview is created with `status` `SCHEDULED` and `outcome` null, and the parent case advances to `INTERVIEW_SCHEDULED`.

The interview may be scheduled from two prior case states: from `RFE_RESPONDED`, after the case has cleared an RFE; or directly from `BIOMETRICS_COMPLETED` when no RFE currently sits `OUTSTANDING`. Either path emits an `INTERVIEW_SCHEDULED` audit event.

Completing the interview requires the interview's `status` to be `SCHEDULED`, the current time to be at or after the recorded `scheduled_at`, and the officer to supply an `outcome` drawn from `RECOMMEND_APPROVAL`, `RECOMMEND_DENIAL`, or `CONTINUED`. On completion the interview's `status` becomes `COMPLETED`, the supplied `outcome` is recorded, the parent case advances to `READY_FOR_DECISION`, and a `STATUS_CHANGED` audit event is emitted. Marking an interview as `NO_SHOW` requires that the current time be more than 24 hours past the scheduled time; the parent case remains in `INTERVIEW_SCHEDULED`. Interviews can also become `CANCELLED` automatically when a parent decision or withdrawal cascade reaches them (see §3.7).

For non-I-485 cases — `I-130`, `I-765`, and `I-131` — there is no interview. Once biometrics are complete (and no RFE is outstanding), an officer manually advances the case to `READY_FOR_DECISION` through the ready-for-decision capability. That advancement emits a `STATUS_CHANGED` audit event.

### 3.7. Decision Recording and the I-130 → I-485 Cascade

A case in `READY_FOR_DECISION` is adjudicated by an `Officer` (or `Supervisor`) through the decide action, which carries a `decision` value of `APPROVE` or `DENY` and an optional `denial_reason`. Approval is rejected with `ERR_PRIORITY_DATE_NOT_CURRENT` when the case's `CaseTypeConfig.requires_priority_date_current` is true and its `priority_date_status` is anything other than `CURRENT`. Approval is also rejected (forcing the officer to deny instead) when the most recent completed interview's `outcome` is `RECOMMEND_DENIAL`; an officer may approve when the interview outcome is `RECOMMEND_APPROVAL` or `CONTINUED`. Denial requires the officer to supply a `denial_reason` drawn from `OFFICER_DENIAL` or `INELIGIBLE`; the other two members of the denial-reason set, `RFE_TIMEOUT` and `ABANDONMENT`, are reserved for system-driven outcomes.

Recording an approval pins `decision_at` to the present instant and transitions the case to `APPROVED`. When the case is an I-130, the approval has a two-hop cascade onto dependent I-485 filings. In the first hop, for every dependent I-485 whose `linked_i130_case_id` references this case and whose `priority_date` is currently null, the system sets the dependent's `priority_date` to this I-130's `priority_date`. In the second hop, for each such dependent updated in the first hop, the system recomputes that dependent's `priority_date_status` against the latest visa bulletin using the priority-date currency rules. A `DECISION_RECORDED` audit event is emitted on the parent I-130.

Recording a denial pins `decision_at` to the present instant, records the supplied `denial_reason`, and transitions the case to `DENIED`. When the case is an I-130, denial cascades in two hops onto dependent I-485 filings. In the first hop, for every dependent I-485 whose `linked_i130_case_id` references this case and whose own `status` is not already one of `APPROVED`, `DENIED`, or `WITHDRAWN`, the system forces that dependent's `status` to `DENIED`, sets its `denial_reason` to `INELIGIBLE`, and pins its `decision_at` to the same instant. In the second hop, for each dependent I-485 forced into `DENIED` in the first hop, any `Biometrics` row with `status` `SCHEDULED` on the dependent is set to `CANCELLED` and any `Interview` row with `status` `SCHEDULED` on the dependent is set to `CANCELLED`. A `DECISION_RECORDED` audit event is emitted on the I-130 and an additional `CaseEvent` is emitted on each affected dependent.

Two terminal-state races on the same case — for instance, a petitioner withdrawing while an officer approves a `READY_FOR_DECISION` case — are resolved first-writer-wins on `Case.status`; the loser is rejected with `ERR_INVALID_STATE` and observes the case already in its new terminal state.

### 3.8. Withdrawal Paths

A `Petitioner` may withdraw their case to terminal `WITHDRAWN`. From `DRAFT` the withdrawal has no precondition. From `FILED` the withdrawal requires that no `Biometrics` row on the case has reached `COMPLETED`. From `BIOMETRICS_SCHEDULED` withdrawal also requires no completed biometrics chain, and the withdrawal additionally cancels any still-`SCHEDULED` biometrics by setting their `status` to `CANCELLED`. Every withdrawal path pins `decision_at` to the present instant and emits a `STATUS_CHANGED` audit event capturing the source state to `WITHDRAWN`.

### 3.9. Visa Bulletin Maintenance and Chart-in-Effect

The Department of State publishes the Visa Bulletin once per month, with two charts side by side: the Final Action chart and the Dates for Filing chart. A `Supervisor` publishes individual `VisaBulletin` rows into the system. Each row identifies its `bulletin_month` in `YYYY-MM` form (only months from year 1000 onward and month numbers 01 through 12 are accepted), its `chart_type` (`FINAL_ACTION` or `DATES_FOR_FILING`), its `preference_category` (`F1`, `F2A`, `F2B`, `F3`, or `F4`; immediate-relative cases never appear in the bulletin), its `country` (a three-letter uppercase ISO 3166-1 alpha-3 code, or the literal `ROW` for the rest-of-world catch-all), and its `cutoff_date` (an ISO 8601 calendar date, or the literal `CURRENT`, or the literal `UNAVAILABLE`). The server pins `published_at` to the moment of publication.

A `Supervisor` also configures the `chart_in_effect` policy for I-485 adjudication by supplying a `chart_type` of `FINAL_ACTION` or `DATES_FOR_FILING`. Changing the chart in effect does not retroactively change any stored `priority_date_status`; it changes the answer the next time priority-date currency is computed. The default value is `FINAL_ACTION`.

A case's `priority_date_status` is recomputed in three situations beyond initial filing: when an I-130 approval cascades to update the dependent I-485's `priority_date`, when a newer `VisaBulletin` row arrives that could shift the answer, and when an `Officer` or `Supervisor` explicitly requests refresh on a case. The refresh action emits a `PRIORITY_DATE_RECOMPUTED` audit event capturing the prior and new `priority_date_status` values in `from_value` and `to_value`. The mechanics — pinning the latest month by lexical `bulletin_month` order with `published_at` tie-break, selecting on `(chart_type, preference_category, country)` with `country_of_chargeability` beating `ROW`, interpreting `CURRENT`/`UNAVAILABLE`/real-date semantics with strict less-than on the date variant, and detecting retrogression by comparing against the previously stored status — are pinned in §2.9.

### 3.10. The Clock-Advance Sweep

A `Supervisor` may advance the logical server clock to a supplied `to` instant, expressed as an ISO 8601 UTC timestamp. The action is intended for deterministic testing. Advancing the clock runs every time-triggered sweep against the new server time and returns an object whose fields are `now` (the new server clock value), `expired_rfes` (the count of RFEs swept to `EXPIRED`), and `auto_denied_cases` (the count of cases auto-denied as a result).

The RFE expiry sweep iterates every RFE whose `status` is `OUTSTANDING` and whose `deadline_at` has been strictly exceeded by the new server time. Each such RFE has its `status` set to `EXPIRED`, and its parent case transitions to `DENIED` with `denial_reason` set to `RFE_TIMEOUT` and `decision_at` set to the moment of expiry (the first cascade hop). For each case auto-denied above whose `case_type` is `I-130`, the cascade extends to any dependent I-485 (where `linked_i130_case_id` references the just-denied I-130) with a non-terminal `status`: that dependent is also forced to `DENIED` with `denial_reason` set to `INELIGIBLE` (the second cascade hop). For each dependent I-485 denied in the second hop, any `SCHEDULED` `Biometrics` row and any `SCHEDULED` `Interview` row on the dependent are set to `CANCELLED` (the third cascade hop). The current server clock can also be read for test introspection.

### 3.11. Live Case Summary and the Completeness Score

A live summary view returns a snapshot for a single case: its persistent fields, the count of its children, and a computed completeness score (the live-summary variant of the calculation). The completeness score is a weighted multi-factor index on a 0-to-100 scale used by officers for triage ranking. Five factors feed it.

The status factor reads exactly from the case's `status`: `DRAFT` contributes a raw 0.00, `FILED` contributes 0.10, `BIOMETRICS_SCHEDULED` contributes 0.20, `BIOMETRICS_COMPLETED` contributes 0.40, `RFE_ISSUED` contributes 0.30, `RFE_RESPONDED` contributes 0.50, `INTERVIEW_SCHEDULED` contributes 0.70, `READY_FOR_DECISION` contributes 0.90, and each of `APPROVED`, `DENIED`, and `WITHDRAWN` contributes 1.00. The biometrics factor is 1.00 when there exists at least one `Biometrics` row on the case with `status` equal to `COMPLETED` and is 0.00 otherwise. The RFE factor is 1.00 when either the matching `CaseTypeConfig.requires_priority_date_current` is false or no `RFE` row on the case is currently in `OUTSTANDING` status, and is 0.00 otherwise. The interview factor is 1.00 when there exists at least one `Interview` row on the case with `status` equal to `COMPLETED`; otherwise it is 0.50 when there exists at least one `Interview` row in `SCHEDULED`; otherwise it is 0.00. The priority factor is 1.00 when `priority_date_status` is `CURRENT` or `NOT_APPLICABLE`, 0.50 when `priority_date_status` is `NOT_CURRENT`, and 0.00 when `priority_date_status` is `RETROGRESSED`.

The weights are fixed at 0.40 for status, 0.20 for biometrics, 0.10 for RFE, 0.15 for interview, and 0.15 for priority — summing to 1.00. The rounding order is pinned: each factor's weighted product (raw factor multiplied by weight) is rounded to two decimal places half-up first, then the five rounded per-factor scores are summed, then the sum is multiplied by 100, then that product is rounded to a whole number half-up, and finally the result is clamped into the inclusive 0-to-100 integer range. The live-summary variant is recomputed on every read and is never persisted to the case row. The snapshot-at-decision variant is recomputed at the moment a case transitions to `APPROVED` or `DENIED`, persisted into the matching `CaseEvent.to_value` of the `DECISION_RECORDED` event, and never overwritten thereafter.

### 3.12. List, Read, and Audit Capabilities

`Officer`s and `Supervisor`s can list cases system-wide with filtering by `status`, `case_type`, `petitioner_id`, `beneficiary_id`, or `priority_date_status`, paginated with `limit` and `offset`. `VisaBulletin` rows can be listed and filtered by `bulletin_month`, `chart_type`, `preference_category`, and `country`. A case's audit feed, returning its `CaseEvent` history, can be paged with `limit` and `offset`. Single-resource reads (a petitioner, a beneficiary, a case, a biometrics appointment, an RFE, an interview, a case-type configuration) honour the ownership rules described in §2.1.

## 4. Endpoint Definitions

All endpoints are mounted under the system. Endpoints that create a new resource respond with HTTP 201 on success; endpoints that modify, read, or trigger sweeps on existing resources respond with HTTP 200. All requests must carry the `X-User-ID` and `X-User-Role` headers, and any failure follows the validation order pinned in §2.4.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST   | `/petitioners` | Create a petitioner profile | `Petitioner`, `Officer`, `Supervisor` |
| GET    | `/petitioners/{petitioner_id}` | Fetch a petitioner | `Petitioner`, `Officer`, `Supervisor` |
| POST   | `/petitioners/{petitioner_id}/beneficiaries` | Create a beneficiary under a petitioner | `Petitioner`, `Officer`, `Supervisor` |
| GET    | `/beneficiaries/{beneficiary_id}` | Fetch a beneficiary | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| POST   | `/admin/case-type-config` | Upsert a case-type configuration row (idempotent on `case_type`) | `Supervisor` |
| GET    | `/admin/case-type-config/{case_type}` | Fetch a case-type configuration | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| POST   | `/cases` | Create a case in DRAFT | `Petitioner`, `Officer` |
| GET    | `/cases/{case_id}` | Fetch a case (including computed `priority_date_status`) | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| GET    | `/cases` | List cases with filtering and pagination | `Officer`, `Supervisor` |
| POST   | `/cases/{case_id}/file` | Transition `DRAFT` → `FILED`; mints `receipt_number`; triggers priority-date recomputation | `Petitioner` |
| POST   | `/cases/{case_id}/biometrics` | Schedule biometrics; transitions case to `BIOMETRICS_SCHEDULED` | `Officer` |
| POST   | `/cases/{case_id}/rfe` | Issue an RFE; transitions case to `RFE_ISSUED`; sets `Case.rfe_deadline` | `Officer` |
| POST   | `/cases/{case_id}/interview` | Schedule an AOS interview (I-485 only) | `Officer` |
| POST   | `/cases/{case_id}/ready-for-decision` | Manually advance a non-I-485 case to `READY_FOR_DECISION` | `Officer` |
| POST   | `/cases/{case_id}/decide` | Record `APPROVE` or `DENY` with optional `denial_reason` | `Officer`, `Supervisor` |
| POST   | `/cases/{case_id}/withdraw` | Petitioner withdraws the case (terminal `WITHDRAWN`) | `Petitioner` |
| POST   | `/cases/{case_id}/refresh-priority-date` | Force a recomputation of `priority_date_status` against the latest Visa Bulletin | `Officer`, `Supervisor` |
| GET    | `/cases/{case_id}/summary` | Live snapshot including completeness score and child counters | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| GET    | `/cases/{case_id}/events` | Audit feed for a case | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| GET    | `/biometrics/{biometrics_id}` | Fetch a biometrics appointment | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| POST   | `/biometrics/{biometrics_id}/complete` | Mark a biometrics appointment `COMPLETED` | `Officer` |
| POST   | `/biometrics/{biometrics_id}/no-show` | Mark a biometrics appointment `NO_SHOW` | `Officer` |
| POST   | `/biometrics/{biometrics_id}/reschedule` | Reschedule a biometrics appointment; creates a fresh `SCHEDULED` row with `reschedule_count + 1` | `Officer` |
| GET    | `/rfes/{rfe_id}` | Fetch an RFE | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| POST   | `/rfes/{rfe_id}/respond` | Beneficiary submits an RFE response | `Beneficiary`, `Petitioner` |
| GET    | `/interviews/{interview_id}` | Fetch an interview | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| POST   | `/interviews/{interview_id}/complete` | Officer marks the interview `COMPLETED` with an outcome | `Officer` |
| POST   | `/interviews/{interview_id}/no-show` | Mark interview `NO_SHOW` (no earlier than `scheduled_at` + 24h) | `Officer` |
| POST   | `/admin/visa-bulletin` | Publish a `VisaBulletin` row | `Supervisor` |
| GET    | `/admin/visa-bulletin` | List Visa Bulletin rows with filtering | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |
| POST   | `/admin/visa-bulletin/chart-in-effect` | Configure which chart governs priority-date currency for I-485 | `Supervisor` |
| POST   | `/_clock/advance` | Advance the server clock to a supplied `to` instant; run RFE-expiry sweeps and cascades | `Supervisor` |
| GET    | `/_clock` | Read the current server clock (test introspection) | `Petitioner`, `Beneficiary`, `Officer`, `Supervisor` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING_HEADERS` | 401 |
| `ERR_AUTH_UNKNOWN_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_RFE_ALREADY_OUTSTANDING` | 409 |
| `ERR_BIOMETRICS_ALREADY_SCHEDULED` | 409 |
| `ERR_BIOMETRICS_TOO_SOON` | 422 |
| `ERR_INTERVIEW_TOO_SOON` | 422 |
| `ERR_INTERVIEW_NOT_APPLICABLE` | 422 |
| `ERR_BIOMETRICS_RESCHEDULE_LIMIT` | 409 |
| `ERR_BIOMETRICS_RESCHEDULE_TOO_LATE` | 422 |
| `ERR_RFE_DEADLINE_PASSED` | 409 |
| `ERR_I485_MISSING_APPROVED_I130` | 422 |
| `ERR_PRIORITY_DATE_NOT_CURRENT` | 409 |
| `ERR_RECEIPT_NUMBER_COLLISION` | 409 |
