# Ethics & Financial-Disclosure Filing API — Product Requirements Document

## 1. Introduction

Public-sector ethics authorities carry a recurring administrative burden: they must know who is required to disclose their finances, whether those officials filed on time, what gifts and travel they accepted, when they stepped aside from a conflict, and how allegations of misconduct were resolved. This API is the system of record for that entire compliance apparatus. It maintains a registry of public officials (the **filers**), governs the annual and transactional disclosure statements they submit, tracks reportable gifts and sponsored travel against statutory limits, records conflict-of-interest recusals, assesses and collects late-filing penalties, and drives the complaint-to-adjudication pipeline that can culminate in a formal sanction.

The design goal is a defensible audit trail in which every derived number — an outstanding penalty balance, an annual gift aggregate, a public-disclosure visibility flag — is recomputed deterministically from primitive events rather than hand-edited. Because the same statement can be filed late, returned for correction, resubmitted, accepted, published, superseded by an amendment, or flagged by a sustained complaint, the lifecycle rules are cyclic and cross-referential. Segregation of duties is a first-class concern: the official who is the subject of a matter, the investigator who opens the case, and the adjudicator who decides it are deliberately kept distinct. Throughout, monetary reasoning is performed in whole cents, and all time-based rules (lateness, training expiry, recusal windows) read a single server-controlled logical clock so that behavior is reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A syntactically authenticated request whose role is not permitted to invoke the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `Registrar`, `Filer`, `EthicsOfficer`, `Investigator`, `Adjudicator`, and `Public`.

- A `Registrar` administers jurisdictions, the filer registry, filing periods, public-disclosure publishing, and the test-driving logical clock.
- A `Filer` is a public official acting on their own records — statements, gift reports, recusals, training, and penalty payments.
- An `EthicsOfficer` reviews statements (accepting or returning them), screens complaints, waives penalties, and reopens investigations.
- An `Investigator` opens and conducts investigations on screened complaints.
- An `Adjudicator` decides investigations but may not adjudicate a case they investigated.
- A `Public` principal is an unauthenticated-tier reader of published disclosures and may file complaints.

Role identity binds to resources as follows. When `X-User-Role` is `Filer`, the `X-User-ID` is the `id` of the acting `Filer`; ownership checks on any resource that references a filer compare that resource's `filer_id` to `X-User-ID`. A `Filer` acting on a statement, gift report, recusal, penalty, or training record it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `Registrar`, `EthicsOfficer`, `Investigator`, `Adjudicator`, or `Public`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, an `Investigator`'s identifier is written to `assigned_investigator_id` when an investigation is opened, and an `Adjudicator`'s identifier is written to `adjudicator_id` when a decision is rendered — but it is never compared to any entity's `id` for ownership.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip; it defaults to 0 and must be zero or greater. A request whose `limit` falls outside the range of 1 through 100 inclusive, or whose `offset` is negative, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. List responses populate the `limit`, `offset`, `total_count`, and `has_more` fields in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this system — `Jurisdiction`, `Filer`, `FilingPeriod`, `Statement`, `GiftReport`, `RecusalEntry`, `Penalty`, `Complaint`, `Investigation`, and `TrainingRecord` — carries a uniform set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, stamped when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that begins at 1 and increments by 1 on every mutation, used for optimistic concurrency control.

Whenever the server recomputes a derived attribute on a resource — for example, refreshing a filer's `compliance_status` or `outstanding_penalty_cents` — that recomputation is a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Monetary Values, Precision, and Rounding

All monetary quantities are integers denominated in whole cents; there are no fractional cents in stored values. Where a formula produces a non-integer intermediate — most notably the mileage component of travel valuation, which uses a per-mile rate expressed with a fractional cent — the result is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up). The specific points at which rounding is applied, and their ordering relative to summation, are stated with each calculation in Section 3; the general rule is that penalty amounts and per-leg travel values are rounded half-up to whole cents.

### 2.6. Optimistic Concurrency Control on Publication

Publishing an accepted statement to public disclosure is guarded by optimistic concurrency control. A publish request must carry `expected_statement_version`, the `version` of the target `Statement` that the client last observed. If `expected_statement_version` does not equal the statement's current `version`, the publish is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects the re-publish case: if an amendment, a return, or a resubmission has advanced the statement's `version` between the client's read and the publish attempt, the snapshot the client intended to make public is no longer current, and the stale request is refused rather than silently publishing outdated content. No other endpoint accepts or requires a version field; only publication is version-checked.

### 2.7. Cascading Consistency and Public-Disclosure Visibility

Several operations mutate more than one resource in a single atomic step, and the system guarantees these cascades run to completion. Accepting a statement can finalize a linked late penalty, which in turn adjusts the owning filer's outstanding-penalty ledger and compliance standing, which in turn can pull that filer's published statements out of public view. Sustaining an investigation substantiates its complaint, which can flag the subject statement, which can likewise withhold it from public view. Paying or waiving a penalty reverses the ledger effect and can restore visibility. Each of these secondary effects is specified in the workflow narratives of Section 3; the governing principle here is that derived state (`compliance_status`, `outstanding_penalty_cents`, `reportable_gift_total_cents`, `open_recusal_count`, `training_status`, `public_status`) is always reconciled immediately and never left inconsistent between requests.

Public visibility of a statement is carried by `public_status`, one of `NOT_PUBLISHED`, `PUBLISHED`, or `WITHHELD`. A statement enters `PUBLISHED` only through an explicit publication by a `Registrar`; it can be moved to `WITHHELD` automatically when its filer becomes delinquent or when it is flagged, and it can be moved from `WITHHELD` back to `PUBLISHED` automatically when the filer returns to good standing.

### 2.8. Left-to-Right Path Validation

For endpoints whose path names a resource by identifier, the referenced resource must exist or the request fails with `ERR_NOT_FOUND` (HTTP 404). Where a path nests one resource under another — for instance, opening an investigation under a complaint, where the complaint identifier appears in the path — the identifiers are validated left to right, and the first identifier that does not resolve to an existing resource produces the `ERR_NOT_FOUND`. The same 404 applies to foreign keys carried in a create request body: a `jurisdiction_id`, `filer_id`, `filing_period_id`, `statement_id`, or `complaint_id` that does not reference an existing row causes the create to fail with `ERR_NOT_FOUND`.

### 2.9. The Compliance Ledger and Delinquency Gate

Each filer carries a conserved penalty ledger in `outstanding_penalty_cents`: at all times it equals the sum of `assessed_amount_cents` across that filer's penalties whose status is `ASSESSED`. Penalties that are still accruing, that have been paid, or that have been waived contribute nothing to this sum. Whenever a penalty is assessed, paid, or waived, the ledger is recomputed and the filer's `compliance_status` is re-derived: the filer is `COMPLIANT` when `outstanding_penalty_cents` is at most the delinquency block threshold of 10000 cents (that is, 100 dollars), and `DELINQUENT` when it exceeds that threshold. This same threshold gates new statement submissions, as described in Section 3.4.

### 2.10. The Logical Clock

All time-sensitive rules — statement lateness, training validity and expiry, recusal-interval overlap — read a single server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to real time before it is set. A `Registrar` may advance the clock to a supplied instant for test-driving purposes; the payload supplies the target instant in `to_iso8601`. Timestamps the server stamps from this clock — such as `submitted_at`, `published_at`, `enrolled_at`, `completed_at`, and `expires_at` — reflect the logical clock's value at the moment of the operation.

### 2.11. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the reported `error_id` is deterministic. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) role authorization, yielding `ERR_UNAUTHORIZED`; (3) request-body well-formedness — required fields present, enum values legal, integer fields non-negative — yielding `ERR_VALIDATION`; (4) existence of path-referenced resources, yielding `ERR_NOT_FOUND`; (5) existence of body foreign keys, also yielding `ERR_NOT_FOUND`; (6) resource ownership for filer-owned mutations, yielding `ERR_NOT_RESOURCE_OWNER`; (7) that the target is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE`; and then the endpoint-specific business rules described in Section 3 — segregation of duties (`ERR_SOD_CONFLICT`), training currency (`ERR_TRAINING_NOT_CURRENT`), recusal overlap (`ERR_RECUSAL_OVERLAP`), period overlap (`ERR_PERIOD_OVERLAP`), duplicate statement (`ERR_DUPLICATE_STATEMENT`), single-gift limit (`ERR_GIFT_LIMIT_EXCEEDED`), delinquency block (`ERR_FILER_DELINQUENT`), annual gift limit (`ERR_GIFT_ANNUAL_LIMIT_EXCEEDED`), publication staleness (`ERR_STALE_VERSION`), closed period (`ERR_PERIOD_CLOSED`), gift-kind payload shape (`ERR_INVALID_GIFT_KIND_PAYLOAD`), and pagination bounds (`ERR_PAGINATION_INVALID`). Authentication and authorization always precede existence checks, which always precede state and business checks.

## 3. Business Logic & Workflows

### 3.1. Jurisdictions and the Filer Registry

The unit of governance is the **jurisdiction**, created by a `Registrar` with a `name` and a set of monetary policy limits. Four penalty parameters and two gift parameters are configured per jurisdiction: `penalty_base_fee_cents`, the flat base fee applied to any late statement before per-day accrual, defaulting to 5000; `penalty_daily_rate_cents`, the tier-1 per-day accrual rate, defaulting to 250; `penalty_cap_cents`, the absolute ceiling on any single late-filing penalty, defaulting to 50000; `gift_single_limit_cents`, the per-event ceiling on a single gift's net reportable value, defaulting to 5000; and `gift_annual_source_limit_cents`, the per-source per-calendar-year cumulative ceiling on net reportable gifts, defaulting to 25000. When a policy field is omitted at creation, its stated default applies.

A `Registrar` populates the registry by adding each public official as a **filer**, supplying the `jurisdiction_id` they belong to, their `full_name`, their `official_title`, a `filer_category`, and optionally an `email`. The `filer_category` is one of `ELECTED`, `APPOINTED`, `SENIOR_STAFF`, or `CANDIDATE`, and it selects the multiplier used when the filer's late penalties are finalized. A filer's registry `status` is one of `ACTIVE`, `INACTIVE`, or `SEPARATED`, defaulting to `ACTIVE`; only an `ACTIVE` filer may submit statements or file gift reports. A `Registrar` may later change a filer's registry standing.

Beyond these inputs, a filer exposes several server-derived attributes that reflect the filer's compliance posture and are never set directly by clients: `compliance_status`, `outstanding_penalty_cents`, `reportable_gift_total_cents`, `open_recusal_count`, and `training_status`. Reading a filer returns all of these. The `reportable_gift_total_cents` is a rolling aggregate — the sum of net reportable values across the filer's non-disposed gift reports in the current calendar year — and `open_recusal_count` is the conserved number of the filer's recusals currently in `DECLARED` status.

### 3.2. Filing Periods

A `Registrar` opens a **filing period** to define a reporting cycle. A period carries the owning `jurisdiction_id`, a human `label` such as "CY2025 Annual", a `statement_type` of either `ANNUAL` or `TRANSACTIONAL`, and three instants: `coverage_start` and `coverage_end`, the inclusive lower and upper bounds of the reporting-coverage interval, and `due_at`, the filing deadline after which a submission is late. Its `status` is `OPEN` or `CLOSED`, defaulting to `OPEN`; an `OPEN` period accepts filings and a `CLOSED` one does not.

Coverage intervals for the same jurisdiction and statement type may not overlap. Because both bounds are inclusive, the overlap test treats the interval as closed on both ends: two periods conflict if their closed `coverage_start`-through-`coverage_end` ranges share any instant, including a shared endpoint where one period ends exactly when another begins. An attempt to open a period whose closed coverage interval overlaps an existing period of the same `jurisdiction_id` and `statement_type` is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409).

### 3.3. Statements: Drafting, Submission, and Lateness

A `Filer` prepares disclosure by creating a **statement** in `DRAFT` status against a filer and period, supplying `filer_id`, `filing_period_id`, and optionally the disclosure `content` (an opaque payload of assets, income, and positions), a `redaction_level`, and, when the statement amends a prior one, a `supersedes_statement_id`. At creation the statement's `statement_type` is copied from the linked period's `statement_type`, and `redaction_level` defaults to `FULL` (the alternative being `REDACTED`). The referenced period must be `OPEN`; creating a statement against a `CLOSED` period is rejected with `ERR_PERIOD_CLOSED` (HTTP 409). At most one non-superseded statement may exist for a given `filer_id` and `filing_period_id` pair; a second one is rejected with `ERR_DUPLICATE_STATEMENT` (HTTP 409).

Submission moves the statement from `DRAFT` to `SUBMITTED` and may optionally carry an `attestation`. Four preconditions guard the initial submission: the statement is in `DRAFT`; the owning filer's registry `status` is `ACTIVE`; the owning filer's `training_status` is `CURRENT`; and the owning filer's `outstanding_penalty_cents` is at most the delinquency block threshold of 10000 cents. Additionally, the linked period must still be `OPEN`. A submission by a filer whose training has lapsed is rejected with `ERR_TRAINING_NOT_CURRENT` (HTTP 422); a submission by a filer whose outstanding penalties exceed the threshold is rejected with `ERR_FILER_DELINQUENT` (HTTP 402); a submission against a closed period is rejected with `ERR_PERIOD_CLOSED`; and a submission from any state other than `DRAFT` (or `RETURNED_FOR_CORRECTION`, below) is rejected with `ERR_INVALID_STATE` (HTTP 409). Only the owning filer may submit; another filer is rejected with `ERR_NOT_RESOURCE_OWNER`.

On submission the server stamps `submitted_at` from the logical clock, captures `due_at_snapshot` from the period's `due_at` (this snapshot, taken at the first submit, anchors all later late math), and derives lateness. The statement `is_late` when `submitted_at` is strictly after `due_at_snapshot`; otherwise it is on time. When on time, `days_late` is 0; when late, `days_late` is the difference between `submitted_at` and `due_at_snapshot` in seconds divided by 86400, rounded up to the next whole day. If the submission is late, the server creates a companion **penalty** of type `LATE_FILING` in `ACCRUING` status linked to this statement, stamping its `provisional_amount_cents` per the provisional late-penalty estimate described in Section 3.4.

A `RETURNED_FOR_CORRECTION` statement may be resubmitted, moving it back to `SUBMITTED`. This cyclic resubmission requires only that the statement be in `RETURNED_FOR_CORRECTION`, that the owning filer be `ACTIVE`, and that the filer's `training_status` be `CURRENT`; it re-stamps `submitted_at` from the logical clock and recomputes `is_late` and `days_late` against the previously captured `due_at_snapshot`.

### 3.4. Late-Filing Penalties: Provisional Estimate and Final Assessment

A late penalty carries two monetary figures computed at two different moments. The **provisional** figure, stamped on `provisional_amount_cents` at submit time, is a deliberately simple estimate: the jurisdiction's `penalty_base_fee_cents` plus its `penalty_daily_rate_cents` multiplied by `days_late`. It ignores the tier structure, the category multiplier, and the cap.

The **final** figure is computed when an `EthicsOfficer` accepts the statement and is stamped on the penalty's `assessed_amount_cents`. It applies the full tiered formula. First a per-day tier rate is selected from `days_late`: if `days_late` is at most 30, the tier rate equals `penalty_daily_rate_cents`; if `days_late` is greater than 30 but at most 90, the tier rate is `penalty_daily_rate_cents` multiplied by 2; and if `days_late` is greater than 90, the tier rate is `penalty_daily_rate_cents` multiplied by 3. A raw amount is then formed as `penalty_base_fee_cents` plus the product of the tier rate, `days_late`, and the filer's category multiplier, where the category multiplier is 2.0 for `ELECTED`, 1.5 for `APPOINTED`, 1.0 for `SENIOR_STAFF`, and 1.0 for `CANDIDATE`. The raw amount is rounded half-up to whole cents, and the final assessed amount is the lesser of that rounded value and the jurisdiction's `penalty_cap_cents`. The penalty also records a `days_late` snapshot copied from the driving statement, and carries `filer_id`, `statement_id` (set for late-filing penalties), and `penalty_type`.

A penalty's lifecycle status is one of `ACCRUING`, `ASSESSED`, `PAID`, or `WAIVED`. When acceptance finalizes a late penalty, that penalty moves `ACCRUING → ASSESSED` with its `assessed_amount_cents` set as above; the assessment increments the owning filer's `outstanding_penalty_cents` by `assessed_amount_cents` and recomputes `compliance_status`. If that recomputation flips the filer to `DELINQUENT`, every one of that filer's statements currently `PUBLISHED` is moved to `WITHHELD`.

A `Filer` pays an assessed penalty they own, optionally supplying a `payment_ref`; this requires the penalty to be `ASSESSED` and moves it `ASSESSED → PAID`, decrementing the filer's `outstanding_penalty_cents` by `assessed_amount_cents` and recomputing `compliance_status`. If that recomputation flips the filer back to `COMPLIANT`, every one of that filer's `WITHHELD` statements is restored to `PUBLISHED`. An `EthicsOfficer` may instead waive an assessed penalty, optionally supplying a `waive_reason`; this likewise requires the penalty to be `ASSESSED`, moves it `ASSESSED → WAIVED`, decrements the filer's `outstanding_penalty_cents` by `assessed_amount_cents`, and recomputes `compliance_status`. Attempting to pay or waive a penalty that is not `ASSESSED` is rejected with `ERR_INVALID_STATE`.

### 3.5. Statement Review, Publication, and Amendment

An `EthicsOfficer` reviews a submitted statement and either accepts or returns it, optionally attaching a `review_note` or a `correction_note` respectively. Acceptance requires the statement to be `SUBMITTED` and moves it `SUBMITTED → ACCEPTED`, triggering the late-penalty finalization cascade described in Section 3.4. Returning a statement requires it to be `SUBMITTED`, moves it `SUBMITTED → RETURNED_FOR_CORRECTION`, and increments `correction_round` by 1; the filer then resubmits as described in Section 3.3, forming the cyclic review loop `SUBMITTED ↔ RETURNED_FOR_CORRECTION`. Acting on a statement that is not `SUBMITTED` from either of these operations is rejected with `ERR_INVALID_STATE`.

Once accepted, a statement may be published to public disclosure by a `Registrar`. Publication requires `expected_statement_version` matching the statement's current `version` (see Section 2.6) and optionally a `redaction_level` to apply at publish time; it sets `public_status` to `PUBLISHED`, stamps `published_at` from the logical clock, and increments the statement's `version` by 1. The `redaction_level` recorded on the statement governs whether the `Public` view is shown in `FULL` or `REDACTED` form. When a reader lists statements with the `public` flag set to true, only statements whose `public_status` is `PUBLISHED` are returned.

Amendment is the mechanism by which a filer corrects a statement that has already been accepted: the filer creates a new statement whose `supersedes_statement_id` points at the prior accepted statement. When that amendment is itself accepted, the system transitions the superseded prior statement `ACCEPTED → SUPERSEDED` and sets its `public_status` to `NOT_PUBLISHED`, so the older snapshot leaves public view. `SUPERSEDED` is terminal.

### 3.6. Gift and Travel Reporting

A `Filer` records a **gift report** identifying the `source_name` (the donor), a `gift_kind` of either `GIFT` or `TRAVEL`, and the `received_at` instant that buckets the gift into a calendar year for annual aggregation. Reporting requires the acting filer's `training_status` to be `CURRENT`; a lapsed filer is rejected with `ERR_TRAINING_NOT_CURRENT`. The payload shape depends on `gift_kind`: a `GIFT` must supply a positive `fair_market_value_cents`, and a `TRAVEL` must supply a non-empty `travel_legs` array; a violation of either shape is rejected with `ERR_INVALID_GIFT_KIND_PAYLOAD` (HTTP 400). A filer may also declare `consideration_paid_cents`, the amount they already paid toward the gift, which is subtracted to obtain the net reportable value.

Two values are computed at report time and stored. The **disclosed gross** value, `disclosed_gross_cents`, is the full gross with no consideration subtracted: for a `GIFT` it is `fair_market_value_cents`, and for `TRAVEL` it is the travel valuation described below. The **net reportable** value, `reportable_value_cents`, is the disclosed gross minus `consideration_paid_cents`, floored at zero so it is never negative. These two differ precisely when `consideration_paid_cents` is greater than zero; the gross drives the public-disclosure display while the net drives the limit checks.

For travel, each element of `travel_legs` is an object with `nights`, `nightly_rate_cents`, and `miles`. A leg's raw value is `nights` multiplied by `nightly_rate_cents`, plus `miles` multiplied by the mileage rate of 65.5 cents per mile. The rounding order is pinned: each leg's raw value is rounded half-up to whole cents individually, and only then are the rounded legs summed to yield the travel gross — the legs are never summed before rounding.

Two statutory limits guard reporting. The single-gift limit rejects any report whose net `reportable_value_cents` exceeds the jurisdiction's `gift_single_limit_cents`, with `ERR_GIFT_LIMIT_EXCEEDED` (HTTP 422). The annual per-source limit considers the running aggregate: the sum of net reportable values across the filer's existing non-disposed gift reports from the same `source_name` in the same calendar year as this gift's `received_at`, plus this gift's net value; if that aggregate exceeds the jurisdiction's `gift_annual_source_limit_cents`, the report is rejected with `ERR_GIFT_ANNUAL_LIMIT_EXCEEDED` (HTTP 422). A gift report's `status` is `REPORTED` on creation, and recording it adds its `reportable_value_cents` to the owning filer's `reportable_gift_total_cents`.

A `Filer` may later dispose of a gift they own — returning or reimbursing it — optionally noting a `disposition_method`. Disposal requires the report to be `REPORTED`, moves it `REPORTED → DISPOSED`, and subtracts its `reportable_value_cents` from the filer's `reportable_gift_total_cents`, removing it from the annual aggregate. Because the aggregate only counts non-disposed reports, a disposed gift no longer contributes to future annual-limit checks.

### 3.7. Conflict-of-Interest Recusals

A `Filer` logs a **recusal** to record stepping aside from a matter, supplying `filer_id`, the opaque `matter_id` of the matter recused from, an `effective_start` and `effective_end` bounding the recusal interval, and optionally a `matter_description` and a `reason`. The interval is half-open: `effective_start` is an inclusive lower bound and `effective_end` is an exclusive upper bound. Overlap is scoped per filer and matter: a new recusal conflicts with an existing `DECLARED` recusal on the same `filer_id` and `matter_id` only if their half-open intervals overlap, so two recusals that merely touch at an endpoint (one ending exactly where the next begins) do not conflict. A genuine overlap is rejected with `ERR_RECUSAL_OVERLAP` (HTTP 409). A recusal's `status` is `DECLARED` on creation, and declaring it increments the owning filer's `open_recusal_count` by 1.

The owning `Filer` resolves a recusal once the conflict clears, optionally noting a `resolution_note`. Resolution requires the recusal to be `DECLARED`, moves it `DECLARED → RESOLVED`, and decrements the filer's `open_recusal_count` by 1, compensating the increment applied at declaration. `RESOLVED` is terminal.

### 3.8. Complaints, Investigations, and Sanctions

Anyone in the `EthicsOfficer` or `Public` role may file a **complaint** against a filer, supplying the respondent's `filer_id`, the `allegation` text, an opaque `complainant_ref`, and optionally a `statement_id` naming the specific statement at issue. A complaint's `status` runs `FILED`, then either `SCREENED` or `DISMISSED`, and ultimately `SUBSTANTIATED` when an investigation sustains it.

An `EthicsOfficer` screens a filed complaint, supplying a `decision` and an optional `screen_note`. Screening is a branching fork out of `FILED`: a `decision` directing screening moves the complaint `FILED → SCREENED` and makes it eligible for investigation, while a `decision` directing dismissal moves it `FILED → DISMISSED`. Screening a complaint that is not `FILED` is rejected with `ERR_INVALID_STATE`.

An `Investigator` opens an **investigation** on a screened complaint; the complaint identifier is supplied in the path and an optional `scope_note` in the body. The investigation copies its `filer_id` from the parent complaint and records the opening investigator's `X-User-ID` in `assigned_investigator_id`, which anchors segregation of duties. An investigation's `status` runs `OPEN`, then `SUSTAINED` or `NOT_SUSTAINED`, with `NOT_SUSTAINED` able to cycle back to `OPEN`, and `CLOSED` as the archival terminal.

An `Adjudicator` decides an open investigation, supplying a `decision`, optional `findings`, and an optional `recommended_sanction_cents`; the decision writes the adjudicator's `X-User-ID` to `adjudicator_id`. Adjudication requires the investigation to be `OPEN`, the parent complaint to be `SCREENED`, and the acting `X-User-ID` to differ from the investigation's `assigned_investigator_id`; an adjudicator who is also the assigned investigator is rejected with `ERR_SOD_CONFLICT` (HTTP 409). A decision to sustain moves the investigation `OPEN → SUSTAINED`. On sustaining, the system sets `final_sanction_cents` to the lesser of the jurisdiction's `penalty_cap_cents` and the `recommended_sanction_cents`; transitions the parent complaint `SCREENED → SUBSTANTIATED`; and creates a `SANCTION` penalty already in `ASSESSED` status, linked by `investigation_id`, whose `assessed_amount_cents` equals `final_sanction_cents` (its `provisional_amount_cents` and its `days_late` remain 0), which increments the filer's `outstanding_penalty_cents` and recomputes `compliance_status`. When the complaint substantiates and it carries a `statement_id`, that statement transitions `ACCEPTED → FLAGGED`; if that statement was `PUBLISHED`, its `public_status` is set to `WITHHELD`. A decision to not sustain moves the investigation `OPEN → NOT_SUSTAINED` and transitions the parent complaint `SCREENED → DISMISSED`, with no sanction created.

An `EthicsOfficer` may reopen a not-sustained investigation, optionally noting a `reopen_reason`. Reopening requires the investigation to be `NOT_SUSTAINED`, moves it `NOT_SUSTAINED → OPEN`, and transitions the parent complaint `DISMISSED → SCREENED` to re-open the matter — the cyclic shape `OPEN → NOT_SUSTAINED → OPEN`. A sustained investigation is effectively final and is not reopenable; its archival closure is `SUSTAINED → CLOSED`.

### 3.9. Ethics Training and Certification

A `Filer` enrolls in an ethics course by supplying `filer_id` and a `course_code`; enrollment creates a **training record** in `ENROLLED` status and stamps `enrolled_at` from the logical clock. The owning filer completes the course, optionally supplying a `score`; completion requires the record to be `ENROLLED`, moves it `ENROLLED → COMPLETED`, stamps `completed_at` from the logical clock, sets `expires_at` to `completed_at` plus the training validity window of 365 days, mints a `certificate_no`, and recomputes the filer's `training_status` to `CURRENT`.

A filer's `training_status` reflects the state of their completed courses against the logical clock: it is `CURRENT` when the filer has a completed course whose `expires_at` is strictly after the current clock, `LAPSED` when the latest completed course has expired, and `NONE` when no course has been completed. When the logical clock reaches or passes a completed record's `expires_at`, that record moves `COMPLETED → EXPIRED` and the filer's `training_status` is recomputed to `LAPSED`. Because both statement submission and gift reporting require `training_status` to be `CURRENT`, a lapse blocks those operations until a fresh course is completed.

## 4. Endpoint Definitions

Endpoints that create a new, stand-alone resource return `201 Created`; endpoints that read or that modify an existing resource (including state transitions) return `200 OK`. All request and response bodies use the envelope of Section 2.2; the specific inputs and side effects of each operation are described in the Section 3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/jurisdictions` | Register a jurisdiction with gift/penalty limits | Registrar |
| GET | `/jurisdictions/{id}` | Read a jurisdiction | Registrar, EthicsOfficer, Filer |
| POST | `/filers` | Add a public official to the filer registry | Registrar |
| GET | `/filers/{id}` | Read a filer including computed compliance fields | Registrar, EthicsOfficer, Filer, Investigator, Adjudicator |
| GET | `/filers` | List filers | Registrar, EthicsOfficer |
| PATCH | `/filers/{id}/status` | Change a filer's registry status | Registrar |
| POST | `/filing-periods` | Open a filing period | Registrar |
| GET | `/filing-periods/{id}` | Read a filing period | Registrar, EthicsOfficer, Filer |
| GET | `/filing-periods` | List filing periods | Registrar, EthicsOfficer, Filer |
| POST | `/statements` | Create a DRAFT statement for a filer/period | Filer |
| GET | `/statements/{id}` | Read a statement | Registrar, EthicsOfficer, Filer, Public |
| GET | `/statements` | List statements (public=true returns only PUBLISHED) | Registrar, EthicsOfficer, Filer, Public |
| POST | `/statements/{id}/submit` | Submit or resubmit a statement | Filer |
| POST | `/statements/{id}/accept` | Accept a submitted statement | EthicsOfficer |
| POST | `/statements/{id}/return` | Return a submitted statement for correction | EthicsOfficer |
| POST | `/statements/{id}/publish` | Publish an accepted statement (OCC-guarded) | Registrar |
| POST | `/gift-reports` | Report a gift or travel | Filer |
| GET | `/gift-reports/{id}` | Read a gift report | Registrar, EthicsOfficer, Filer, Public |
| GET | `/gift-reports` | List gift reports | Registrar, EthicsOfficer, Filer, Public |
| POST | `/gift-reports/{id}/dispose` | Dispose (return/reimburse) a reported gift | Filer |
| POST | `/recusals` | Log a conflict/recusal for a matter | Filer |
| GET | `/recusals/{id}` | Read a recusal entry | Registrar, EthicsOfficer, Filer, Public |
| GET | `/recusals` | List recusal entries | Registrar, EthicsOfficer, Filer, Public |
| POST | `/recusals/{id}/resolve` | Resolve a recusal entry | Filer |
| GET | `/penalties/{id}` | Read a penalty | Registrar, EthicsOfficer, Filer |
| GET | `/penalties` | List penalties | Registrar, EthicsOfficer, Filer |
| POST | `/penalties/{id}/pay` | Pay an assessed penalty | Filer |
| POST | `/penalties/{id}/waive` | Waive an assessed penalty | EthicsOfficer |
| POST | `/complaints` | File an ethics complaint against a filer | EthicsOfficer, Public |
| GET | `/complaints/{id}` | Read a complaint | Registrar, EthicsOfficer, Investigator, Adjudicator |
| GET | `/complaints` | List complaints | Registrar, EthicsOfficer, Investigator, Adjudicator |
| POST | `/complaints/{id}/screen` | Screen a complaint (SCREENED or DISMISSED) | EthicsOfficer |
| POST | `/complaints/{id}/investigations` | Open an investigation on a screened complaint | Investigator |
| GET | `/investigations/{id}` | Read an investigation | Registrar, EthicsOfficer, Investigator, Adjudicator |
| GET | `/investigations` | List investigations | Registrar, EthicsOfficer, Investigator, Adjudicator |
| POST | `/investigations/{id}/adjudicate` | Adjudicate an open investigation (SoD-enforced) | Adjudicator |
| POST | `/investigations/{id}/reopen` | Reopen a not-sustained investigation | EthicsOfficer |
| POST | `/training-records` | Enroll a filer in an ethics course | Filer |
| GET | `/training-records/{id}` | Read a training record | Registrar, EthicsOfficer, Filer |
| GET | `/training-records` | List training records | Registrar, EthicsOfficer, Filer |
| POST | `/training-records/{id}/complete` | Mark a training record COMPLETED | Filer |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SOD_CONFLICT` | 409 |
| `ERR_TRAINING_NOT_CURRENT` | 422 |
| `ERR_RECUSAL_OVERLAP` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_DUPLICATE_STATEMENT` | 409 |
| `ERR_GIFT_LIMIT_EXCEEDED` | 422 |
| `ERR_FILER_DELINQUENT` | 402 |
| `ERR_GIFT_ANNUAL_LIMIT_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PERIOD_CLOSED` | 409 |
| `ERR_INVALID_GIFT_KIND_PAYLOAD` | 400 |
| `ERR_PAGINATION_INVALID` | 400 |
