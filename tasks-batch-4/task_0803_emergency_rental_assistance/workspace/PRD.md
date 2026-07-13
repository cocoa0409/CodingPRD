# Emergency Rental Assistance API — Product Requirements Document

## 1. Introduction

The Emergency Rental Assistance Program (ERAP) API coordinates emergency rent relief between three parties who rarely share a single system of record: the tenant household in arrears, the landlord who is owed rent and who ultimately receives the money, and the public program that funds the payment out of a finite pool. Because the money moves directly to the landlord rather than the tenant, an assistance request is fundamentally a **co-application**: the tenant contributes income and hardship information while the landlord contributes the unit, a taxpayer identity (W-9), and a verified rent ledger. Neither half is actionable on its own, and the program cannot commit a cent until both halves are complete and independently checked.

This document specifies the rules a reviewer, an auditor, and a payment operator must all agree on. It governs household income eligibility against area-median-income limits, the divergence between money owed for past months (**arrears**, reconciled chronologically against a payment ledger) and money committed for future months (**prospective** rent, prorated day-by-day), duplicate-benefit protection so the same month is never funded twice, a strict separation of duties between the caseworker who approves an award and the caseworker who issues its payment, and a fraud-and-recapture pathway that can claw a cleared payment back and unwind every downstream balance. Throughout, the program's funding pool and each household's lifetime months-of-assistance cap behave as conserved reservations: they are debited the moment a payment is created and restored the moment it fails or is recaptured.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contracts that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the two public self-registration endpoints must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. When either header is missing, or `X-User-Role` is not one of the roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The two registration endpoints — household registration and landlord registration — are the sole exception: they accept the `Anonymous` principal with no headers at all. When a well-authenticated principal invokes an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles, spelled exactly: `Anonymous`, `Tenant`, `Landlord`, `CaseWorker`, `ProgramAdmin`, and `FraudInvestigator`.

- `Anonymous` is an opaque principal used only for household and landlord self-registration; it is not tied to any persisted entity and is never recorded.
- When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`. Ownership checks on any resource that references a tenant compare the resource's tenant foreign key to `X-User-ID`: for an application, `X-User-ID` must equal the application's `tenant_id`.
- When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`. Ownership checks compare the landlord foreign key to `X-User-ID`: for a landlord record, `X-User-ID` must equal that landlord's own `id`; for an application, unit, or ledger action, `X-User-ID` must equal the application's `landlord_id` (or the unit/ledger's owning landlord).
- When `X-User-Role` is `CaseWorker`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition writes it — as `approved_by_cw_id` on an `Application` at approval and as `issued_by_cw_id` on a `Disbursement` at creation — but never compares it to any entity's `id`.
- When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `verified_by_id` on a `RentLedger` when the ledger is verified or rejected — but does not compare it to any entity's `id`.
- When `X-User-Role` is `FraudInvestigator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

When an `entity_backed` actor (a `Tenant` or `Landlord`) is authenticated and authorized for the endpoint but is not the owner of the target resource, the request is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — programs, tenants, landlords, units, applications, income sources, rent ledgers, ledger lines, disbursements, recertifications, and recapture cases — carries a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp recording the last modification. It is refreshed on every mutation of the resource, including mutations to computed fields.
- `version`: a system-managed integer that starts at its initial value and increments by one on every mutation of the resource.

Whenever a workflow updates a computed field on a resource — for example when an approval pins the award fields on an application, or when a cleared payment advances the application's disbursed total — that update is a mutation: it refreshes `updated_at` and increments `version` on the affected resource. When one operation mutates several entities (a cascade), each mutated entity independently refreshes its own `updated_at` and increments its own `version`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many paths reference several resources at once — an income source or ledger under an application, a ledger line under a ledger, a disbursement under an application. When a request names multiple resources, the system validates their existence in left-to-right path order: program, then tenant, then landlord, then unit, then application, then ledger, then disbursement, then recertification, then recapture-case, to the extent each appears. The first identifier that does not resolve produces the matching not-found error for that resource type — `ERR_PROGRAM_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LEDGER_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RECERT_NOT_FOUND`, or `ERR_RECAPTURE_NOT_FOUND` — each carrying HTTP 404. Body-referenced resources are validated the same way.

### 2.6. Request Validation Ordering

Across every endpoint the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_UNAUTHORIZED`), then existence of every referenced resource (the not-found family), then `entity_backed` ownership (`ERR_FORBIDDEN_OWNERSHIP`), then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409). Business-specific checks follow, in the order laid out in the workflow sections. Structural payload validation — required fields present, enum values drawn from the declared sets, integers and dates well-formed, and declared numeric constraints satisfied — is reported as `ERR_INVALID_REQUEST` (HTTP 400) and is the lowest-priority family, applying to all write endpoints. Where a specific field constraint is called out below (household size at least 1, unit rent greater than zero, an income amount at least zero, and so on), a violation surfaces as `ERR_INVALID_REQUEST`.

### 2.7. The Funding Pool as a Reservation Ledger

Each program holds a finite pool of money. Its `funding_pool_total_cents` is the total allocation, and `funding_pool_remaining_cents` is the total minus the sum of `amount_cents` across every disbursement of that program currently in a reserving state — that is, in `PENDING`, `SENT`, or `CLEARED` status. Reservation happens at the moment a disbursement is created; it is released only when that disbursement moves to `FAILED` or `RECAPTURED`. A program's `status` is a computed reflection of the remaining pool: it is `OPEN` while funds remain and becomes `EXHAUSTED` the instant `funding_pool_remaining_cents` reaches 0. When a release lifts the remaining balance back above 0, a program that was `EXHAUSTED` returns to `OPEN`.

Any operation that would reserve more money than remains is rejected with `ERR_FUNDING_EXHAUSTED` (HTTP 402); fiscal admissibility is a gate, never a silent clamp on the amount.

### 2.8. The Household Months Cap as a Conserved Counter

Every program declares a `months_cap`, the maximum number of assisted months (arrears months plus prospective months combined) a single household may consume across the program; when omitted at program creation it defaults to 18. Each tenant carries `months_used`, a conserved counter equal to the sum of `months_covered` across every disbursement whose application belongs to that tenant and whose status is `PENDING`, `SENT`, or `CLEARED`. Like funds, months are reserved when a disbursement is created and released when it moves to `FAILED` or `RECAPTURED`. Any grant that would push a household's `months_used` above the program's `months_cap` is rejected with `ERR_MONTHS_CAP_EXCEEDED` (HTTP 422).

### 2.9. Monetary Precision and Rounding

All monetary values are integer cents. Sums and reconciliations over integer-cent inputs (income aggregation, arrears reconciliation, award totals) produce integer cents with no rounding. The one place rounding arises is prorating a partial prospective month: that per-month prorated amount is rounded half up to the nearest whole cent, and the rounding is applied to each month individually before the months are summed (round-per-month-then-sum), never by summing unrounded amounts and rounding once. The reported `ami_pct` is an informational floating-point ratio and is not rounded.

### 2.10. Optimistic Concurrency Control on Disbursement Creation

Creating a disbursement against an application is guarded by optimistic concurrency control keyed on the application's `version`. The create request must carry `expected_application_version`, and it must equal the target application's current `version`. Each disbursement creation reserves funds and months and increments the application's `version`; a request that presents an `expected_application_version` older than the application's current `version` has not observed a prior reservation and would over-reserve against the same pinned award. Such a request is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). No other endpoint takes a version field; disbursement creation is the sole holder of this check.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program and Managing Its Funding

A `ProgramAdmin` establishes an ERAP program by supplying its `name`, the total pool `funding_pool_total_cents` (which may not be negative), the per-month rent cap `per_month_max_cents`, and the income-limit table `monthly_income_limit_by_size`. The table maps a household-size string to the monthly countable-income limit in cents for that size; a household is income-eligible when its countable monthly income is at most the limit for its size, and the table encodes the 80%-of-area-median-income line. The optional `months_cap` defaults to 18 assisted months when omitted, and the optional `eligibility_ami_pct` defaults to 0.80 and records what fraction of area median income the limit table represents. On creation the remaining pool is initialized equal to the total, and `status` is set to `OPEN`, or to `EXHAUSTED` immediately if the total is zero.

A `ProgramAdmin` may later revise the pool by supplying a new `funding_pool_total_cents`. The remaining balance is recomputed as the new total minus all outstanding reservations, `status` is recomputed to `OPEN` or `EXHAUSTED`, and the program's `version` is incremented by one. Programs may be read by any authenticated role.

An administrative test-driving capability lets a `ProgramAdmin` set the server's logical clock to a supplied `to_iso8601` instant. The server starts at a logical clock of `2026-03-01T00:00:00Z`; before any such call the clock reads exactly this default and never falls back to wall-clock time.

### 3.2. Registering Households and Landlords; the W-9 Lifecycle

A household registers itself without authentication, supplying `full_name`, `email`, and `household_size` (which must be at least 1). The household is created with `months_used` initialized to 0. A landlord likewise self-registers without authentication, supplying `legal_name` and `email`; the new landlord begins with `w9_status` of `MISSING`.

Before a landlord can be paid, its taxpayer identity must be verified. The landlord submits a W-9 by supplying `tin`, `banking_last4` (the last four digits of the disbursement account), and `mailing_address`; this stores those details and advances `w9_status` from `MISSING` to `SUBMITTED`. Only the owning landlord (`X-User-ID` equal to the landlord's own `id`) may submit. A `ProgramAdmin` then reviews the submission by supplying a `decision`: a decision of `VERIFIED` advances `w9_status` from `SUBMITTED` to `VERIFIED`, while a decision of `REJECTED` advances it from `SUBMITTED` to `REJECTED`. A rejected W-9 is not a dead end — the owning landlord may resubmit, which overwrites `tin`, `banking_last4`, and `mailing_address` and returns `w9_status` from `REJECTED` back to `SUBMITTED` for another review. Attempting a W-9 transition from a state where it is undefined yields `ERR_INVALID_STATE`.

### 3.3. Opening the Co-Application and Completing Its Two Sections

A landlord first registers each rental `Unit` it owns, supplying the unit's `landlord_id` (the owning landlord), `address`, and `monthly_rent_cents` (which must be greater than zero). Units may be listed, optionally filtered by `landlord_id`, as the reverse lookup from landlord to units.

A `Tenant` opens a co-application draft by supplying `program_id`, `tenant_id`, `landlord_id`, `unit_id`, the claimed `monthly_rent_cents`, and `requested_prospective_months`, plus the optional coverage windows: `arrears_start_month` and `arrears_end_month` (inclusive `YYYY-MM` bounds of the arrears window, both null when no arrears are requested), and `prospective_start_date` and `prospective_end_date` (inclusive `YYYY-MM-DD` bounds of the prospective window, both null when none are requested). At creation the application's `status` is `DRAFT`, and both `tenant_section_status` and `landlord_section_status` are `INCOMPLETE`. The named unit's `landlord_id` must equal the application's `landlord_id`; a mismatch is rejected at creation with `ERR_UNIT_LANDLORD_MISMATCH` (HTTP 422). Applications may be fetched individually (the response includes every computed award field) or listed with filters covering the reverse lookup for each foreign key — `tenant_id`, `landlord_id`, `unit_id`, `program_id` — and by `status`.

The application advances only when both parties finish independently. The tenant completes their portion by supplying `hardship_type` (one of `JOB_LOSS`, `REDUCED_INCOME`, `MEDICAL`, or `OTHER`) and `hardship_attested`; this stores both values and sets `tenant_section_status` to `COMPLETE`, and it requires at least one income source already on file for the application. The landlord completes their portion — optionally acknowledging via `ledger_confirmed` — which sets `landlord_section_status` to `COMPLETE` and requires that the unit be set and a rent ledger already submitted for the application.

Once both sections read `COMPLETE`, the owning tenant submits the co-application, advancing `status` from `DRAFT` to `SUBMITTED`. Submission enforces the co-application quorum: if either `tenant_section_status` or `landlord_section_status` is still `INCOMPLETE`, the submission is rejected with `ERR_SECTION_INCOMPLETE` (HTTP 409); a tenant who is not the owner is rejected with `ERR_FORBIDDEN_OWNERSHIP`; and a submit attempted from any status other than `DRAFT` yields `ERR_INVALID_STATE`.

### 3.4. Declaring Income and Determining Eligibility

The tenant adds one or more income sources to the application, each supplying a `source_type` (one of `WAGES`, `SELF_EMPLOYMENT`, `UNEMPLOYMENT`, `SSI`, `TANF`, or `CHILD_SUPPORT`) and a `monthly_amount_cents` (which may not be negative). Each source carries a computed `countable` flag: it is true for `WAGES`, `SELF_EMPLOYMENT`, and `UNEMPLOYMENT`, and false for `SSI`, `TANF`, and `CHILD_SUPPORT`, which are excluded from the area-median-income comparison. Income sources for an application can be listed (the reverse lookup on `application_id`) and fetched individually.

Eligibility is computed when a caseworker approves the application. The application's `countable_monthly_income_cents` is the sum of `monthly_amount_cents` across only those income sources whose `countable` flag is true — the non-countable public-benefit types (`SSI`, `TANF`, `CHILD_SUPPORT`) never enter this sum. The applicable limit is the entry in the program's `monthly_income_limit_by_size` table keyed by the household's `household_size` (as a string). The household is income-eligible — `income_eligible` is true — exactly when `countable_monthly_income_cents` is less than or equal to that limit. The reported `ami_pct` is `countable_monthly_income_cents` divided by the quantity (limit divided by the program's `eligibility_ami_pct`), carried at full floating-point precision for information only. If the household is not income-eligible at approval, the approval is rejected with `ERR_INCOME_INELIGIBLE` (HTTP 422).

### 3.5. The Rent Ledger and the Arrears Calculation

The landlord submits exactly one rent ledger per application (a 1:1 relationship), providing its monthly `lines`. Each entry becomes a `LedgerLine` bound to the ledger via `ledger_id`, and records a `month` (`YYYY-MM`), a `line_type` (one of `CHARGE`, `PAYMENT`, or `ADJUSTMENT`), a `charge_cents` (the rent charged that month, used when the line is a `CHARGE`, defaulting to 0), and a `payment_cents` (the amount paid or credited that month, used when the line is a `PAYMENT` or `ADJUSTMENT`, defaulting to 0). The ledger is created with `status` of `SUBMITTED`. A second ledger for the same application is rejected with `ERR_LEDGER_ALREADY_EXISTS` (HTTP 409). A `ProgramAdmin` verifies or rejects the submitted ledger by supplying a `decision`: `VERIFIED` moves `status` from `SUBMITTED` to `VERIFIED` and `REJECTED` moves it to `REJECTED`; either records the acting admin as `verified_by_id`. Ledgers can be fetched as the reverse lookup on `application_id` (an array of zero or one), and individual ledger lines can be fetched or listed filtered by `ledger_id`.

Arrears owed are reconciled chronologically at approval, not by naive windowed subtraction. All ledger lines of the application's ledger are ordered by `month` ascending and then by `created_at` ascending. Walking that order, each `CHARGE` opens an outstanding balance equal to its `charge_cents`. Each `PAYMENT` or `ADJUSTMENT` contributes a credit equal to its `payment_cents`, and that credit is applied first-in-first-out to the oldest charge that still has an outstanding balance — including charges dated before the arrears window — taking from each the smaller of its remaining balance and the credit still in hand, moving on to the next-oldest charge until the credit is exhausted. After the whole ledger is processed, `arrears_owed_cents` is the sum of the still-outstanding balances on those `CHARGE` lines whose `month` falls within `arrears_start_month` and `arrears_end_month` inclusive; when the arrears window is null it is 0. Because a payment can be absorbed by an older, pre-window charge, in-window arrears can remain higher than a simple in-window charges-minus-payments figure would suggest; the chronological reconciliation is authoritative. The count of calendar months from `arrears_start_month` through `arrears_end_month` inclusive is stored as `arrears_covered_months`, and is 0 when the window is null.

### 3.6. Review, Approval, and Pinning the Award

A `CaseWorker` takes a submitted application under review, moving `status` from `SUBMITTED` to `UNDER_REVIEW`. From review, the caseworker may request more information — moving `status` to `INFO_REQUESTED` and optionally attaching a `note` — after which either the owning tenant or the owning landlord resubmits, moving `status` back to `UNDER_REVIEW`; this request/resubmit pair forms a cycle that may repeat. The caseworker may instead deny the application outright, moving `status` from `UNDER_REVIEW` to `DENIED` and storing the supplied `decision_reason`. A transition attempted from the wrong state anywhere in this loop yields `ERR_INVALID_STATE`.

Approval is the decisive act. It is available only from `UNDER_REVIEW` and, when granted, computes and pins the award and moves `status` to `APPROVED`, recording the acting caseworker's identity as `approved_by_cw_id`. The approval enforces the following gates, evaluated in this order:

1. The landlord's `w9_status` must be `VERIFIED`; otherwise `ERR_W9_NOT_VERIFIED` (HTTP 422).
2. The application's rent ledger `status` must be `VERIFIED`; otherwise `ERR_LEDGER_NOT_VERIFIED` (HTTP 422).
3. `hardship_attested` must be true; otherwise `ERR_HARDSHIP_NOT_ATTESTED` (HTTP 422).
4. The household must be income-eligible as computed in §3.4; otherwise `ERR_INCOME_INELIGIBLE` (HTTP 422).
5. Duplicate-benefit protection on arrears: the arrears window must share no calendar month with the arrears window of any other `APPROVED` or `DISBURSED` application for the same `unit_id`. Overlap is judged on the closed inclusive interval, so two windows that merely abut (one ending the month before the other begins) are allowed, but any shared month is rejected with `ERR_DUPLICATE_BENEFIT` (HTTP 409).
6. Prospective non-overlap: the prospective window must neither overlap nor fall within a one-month buffer of the prospective window of any other `APPROVED` or `DISBURSED` application for the same `tenant_id`. Because of the one-month buffer, even directly adjacent prospective windows are rejected with `ERR_PROSPECTIVE_OVERLAP` (HTTP 409).
7. Months-cap admissibility: the household's `months_used` plus this award's `months_awarded` must not exceed the program's `months_cap`; otherwise `ERR_MONTHS_CAP_EXCEEDED` (HTTP 422).
8. Fiscal admissibility: the program's `funding_pool_remaining_cents` must be at least the pinned `total_award_cents`; otherwise `ERR_FUNDING_EXHAUSTED` (HTTP 402).

The award figures pinned at approval are built as follows. The monthly award is the smaller of the application's `monthly_rent_cents` and the program's `per_month_max_cents`. The arrears award, `arrears_award_cents`, is the smaller of `arrears_owed_cents` (from §3.5) and the product of `arrears_covered_months` and the monthly award. The prospective side first determines how many future months are grantable, `prospective_months_grantable`, as the smallest of three quantities: the tenant's `requested_prospective_months`; the greater of zero and the household's remaining months (the program `months_cap` minus the tenant's `months_used`) reduced by `arrears_covered_months`; and the count of calendar months spanned by `prospective_start_date` through `prospective_end_date`. The prospective award, `prospective_award_cents`, then sums the covered months: for each covered calendar month, if the month is fully covered its contribution is the full monthly award, and if it is only partially covered its contribution is the monthly award multiplied by the covered days in that month and divided by that month's day count, rounded half up to the nearest cent (§2.9). Only the first `prospective_months_grantable` covered months are summed. The pinned `total_award_cents` is `arrears_award_cents` plus `prospective_award_cents`, and `months_awarded` is `arrears_covered_months` plus `prospective_months_grantable`. These computed fields — `countable_monthly_income_cents`, `ami_pct`, `income_eligible`, `arrears_owed_cents`, `arrears_covered_months`, `arrears_award_cents`, `prospective_award_cents`, `total_award_cents`, and `months_awarded` — are all established at this moment and returned on the application.

### 3.7. Direct-to-Landlord Disbursement and Its Lifecycle

Once an application is `APPROVED`, a `CaseWorker` issues payment directly to the landlord. Creating a disbursement requires supplying `amount_cents` (greater than zero), `months_covered` (at least zero), `coverage_kind` (one of `ARREARS`, `PROSPECTIVE`, or `COMBINED`), and `expected_application_version` for the concurrency check of §2.10. Creation is fenced by a strict separation of duties: the creating principal's `X-User-ID` must differ from the application's `approved_by_cw_id`, so the caseworker who approved an award may never issue its payment; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Creation also enforces the award ceiling: the sum of `amount_cents` across all reserving disbursements (those in `PENDING`, `SENT`, or `CLEARED`) including this one must not exceed the pinned `total_award_cents`, and likewise the cumulative `months_covered` must not exceed the remaining awarded months; a breach is rejected with `ERR_AWARD_EXCEEDED` (HTTP 422). When it succeeds, the create reserves funds (`funding_pool_remaining_cents` is reduced by `amount_cents`, driving the program to `EXHAUSTED` if it reaches zero), reserves months (the tenant's `months_used` is increased by `months_covered`), records `issued_by_cw_id`, increments the application's `version` by one, and sets the disbursement `status` to `PENDING`. Disbursements can be listed per application (reverse lookup on `application_id`) or fetched individually.

For the ordering of gates at creation: the application must be in `APPROVED` state (else `ERR_INVALID_STATE`); no fraud hold may be active (§3.9, else `ERR_FRAUD_HOLD`); the reservation must fit within remaining funds (else `ERR_FUNDING_EXHAUSTED`); separation of duties must hold (`ERR_SEGREGATION_OF_DUTIES`); the award ceiling must hold (`ERR_AWARD_EXCEEDED`); and the concurrency version must match (`ERR_STALE_APPLICATION_VERSION`).

A created payment then moves through its lifecycle. A `CaseWorker` marks it sent, storing the optional `payment_reference` and advancing `status` from `PENDING` to `SENT`; this requires the application to still be `APPROVED` and the landlord's `w9_status` to still be `VERIFIED` (else `ERR_W9_NOT_VERIFIED`). A `ProgramAdmin` then clears a sent payment, advancing `status` from `SENT` to `CLEARED`; clearing adds `amount_cents` to the application's `total_disbursed_cents`, and when that running total reaches or exceeds the pinned `total_award_cents` the application's `status` bubbles up from `APPROVED` to `DISBURSED`. Alternatively a `ProgramAdmin` may mark a sent payment failed, advancing `status` from `SENT` to `FAILED`; failing releases the reservation — `funding_pool_remaining_cents` is increased by `amount_cents` (and if that lifts it above zero while the program was `EXHAUSTED`, the program returns to `OPEN`) and the tenant's `months_used` is decreased by `months_covered`. A failed payment is not final: a `CaseWorker` may retry it, advancing `status` from `FAILED` back to `PENDING`, which re-reserves both funds and months. Retry re-checks that the re-reservation fits — `funding_pool_remaining_cents` must be at least `amount_cents` (else `ERR_FUNDING_EXHAUSTED`) and the tenant's `months_used` plus `months_covered` must not exceed the program's `months_cap` (else `ERR_MONTHS_CAP_EXCEEDED`) — and re-reserving funds drives the program back to `EXHAUSTED` if the remaining balance hits zero. This `FAILED`/`PENDING` pair forms a retry cycle. Any of these transitions attempted from the wrong state yields `ERR_INVALID_STATE`.

### 3.8. Recertification: Extending Prospective Assistance

After an application reaches `DISBURSED`, a `CaseWorker` may open a recertification to extend future assistance, supplying `requested_additional_months` (at least 1) and optionally the extension window `new_prospective_start_date` and `new_prospective_end_date`. A recertification opens with `status` of `PENDING`, and can be listed per application (reverse lookup on `application_id`). The caseworker then decides it by supplying a `decision` and an optional `decision_reason`. A decision to deny moves `status` from `PENDING` to `DENIED` and stores the reason. A decision to approve moves `status` from `PENDING` to `APPROVED` and, as a side effect, creates a new child disbursement in `PENDING` status with `coverage_kind` of `PROSPECTIVE` for the additional months, reserving both funds and months exactly as a disbursement creation does. Approval requires that the application still be `DISBURSED`, that the household still be income-eligible, that the tenant's `months_used` plus `requested_additional_months` not exceed the program's `months_cap` (else `ERR_MONTHS_CAP_EXCEEDED`), and that `funding_pool_remaining_cents` be at least the extension cost — `requested_additional_months` multiplied by the smaller of the application's `monthly_rent_cents` and the program's `per_month_max_cents` (else `ERR_FUNDING_EXHAUSTED`). A decision attempted on a recertification not in `PENDING` yields `ERR_INVALID_STATE`.

### 3.9. Fraud Investigation and the Recapture Cascade

A `FraudInvestigator` opens a recapture case against a cleared disbursement by supplying the `application_id`, the `disbursement_id` of the targeted `CLEARED` payment, and a `reason` (one of `DUPLICATE_BENEFIT`, `INCOME_MISREPRESENTATION`, `VACATED_UNIT`, or `OTHER`). The case opens with `status` of `OPEN` and thereby places a fraud hold on the application. While any recapture case for an application is in `OPEN` or `SUBSTANTIATED` status, three operations are blocked and rejected with `ERR_FRAUD_HOLD` (HTTP 409): creating a disbursement, sending a disbursement, and retrying a failed disbursement. Recapture cases can be fetched individually or listed with filters covering the reverse lookup for both foreign keys, `application_id` and `disbursement_id`.

The investigator advances an open case to `SUBSTANTIATED`, or dismisses it — moving `status` from `OPEN` to `DISMISSED`, which lifts the fraud hold. From `SUBSTANTIATED`, the investigator recovers funds, which requires the targeted disbursement to still be `CLEARED` and triggers a depth-three cascade. Recovery sets the case's `recovered_amount_cents` equal to the targeted disbursement's `amount_cents` and moves the case `status` to `RECOVERED`. As its cascade, the targeted disbursement moves from `CLEARED` to `RECAPTURED`, which in turn releases its reservation (the program's `funding_pool_remaining_cents` is increased by `amount_cents`, returning the program to `OPEN` if it was `EXHAUSTED`), releases its months (the tenant's `months_used` is decreased by `months_covered`), reverses the application's ledger (the application's `total_disbursed_cents` is decreased by `amount_cents`), and moves the application's `status` to `CLOSED`. Each entity touched by this cascade independently refreshes its `updated_at` and increments its `version`. An application may reach `CLOSED` only through this recapture path, whether it was `APPROVED` or `DISBURSED` at the time.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create an ERAP program | ProgramAdmin |
| GET | `/programs/{id}` | Fetch a program | ProgramAdmin, CaseWorker, Tenant, Landlord, FraudInvestigator |
| PATCH | `/programs/{id}/funding` | Adjust the program funding pool total | ProgramAdmin |
| POST | `/tenants` | Register a tenant household | Anonymous |
| GET | `/tenants/{id}` | Fetch a tenant | ProgramAdmin, CaseWorker, Tenant, FraudInvestigator |
| POST | `/landlords` | Register a landlord/payee | Anonymous |
| GET | `/landlords/{id}` | Fetch a landlord | ProgramAdmin, CaseWorker, Landlord, FraudInvestigator |
| POST | `/landlords/{id}/w9` | Submit or resubmit the landlord W-9 | Landlord |
| POST | `/landlords/{id}/w9/verify` | Verify or reject a submitted W-9 | ProgramAdmin |
| POST | `/units` | Register a rental unit | Landlord |
| GET | `/units/{id}` | Fetch a unit | ProgramAdmin, CaseWorker, Landlord |
| GET | `/units` | List units (filter by landlord) | ProgramAdmin, CaseWorker, Landlord |
| POST | `/applications` | Open a co-application draft | Tenant |
| GET | `/applications/{id}` | Fetch an application | ProgramAdmin, CaseWorker, Tenant, Landlord, FraudInvestigator |
| GET | `/applications` | List applications (filters) | ProgramAdmin, CaseWorker, Tenant, Landlord, FraudInvestigator |
| PATCH | `/applications/{id}/tenant-section` | Complete the tenant section | Tenant |
| PATCH | `/applications/{id}/landlord-section` | Complete the landlord section | Landlord |
| POST | `/applications/{id}/submit` | Submit the co-application | Tenant |
| POST | `/applications/{id}/review` | Take the application under review | CaseWorker |
| POST | `/applications/{id}/request-info` | Request additional information | CaseWorker |
| POST | `/applications/{id}/resubmit` | Resubmit after an info request | Tenant, Landlord |
| POST | `/applications/{id}/approve` | Approve; compute and pin the award | CaseWorker |
| POST | `/applications/{id}/deny` | Deny the application | CaseWorker |
| POST | `/applications/{id}/income-sources` | Add a household income source | Tenant |
| GET | `/applications/{id}/income-sources` | List an application's income sources | ProgramAdmin, CaseWorker, Tenant |
| GET | `/income-sources/{id}` | Fetch an income source | ProgramAdmin, CaseWorker, Tenant |
| POST | `/applications/{id}/ledger` | Submit the rent ledger and its lines | Landlord |
| GET | `/applications/{id}/ledger` | Fetch the application's rent ledger | ProgramAdmin, CaseWorker, Landlord, Tenant |
| POST | `/applications/{id}/ledger/verify` | Verify or reject the ledger | ProgramAdmin |
| GET | `/ledger-lines/{id}` | Fetch a ledger line | ProgramAdmin, CaseWorker, Landlord |
| GET | `/ledger-lines` | List ledger lines (filter by ledger) | ProgramAdmin, CaseWorker, Landlord |
| POST | `/applications/{id}/disbursements` | Create a direct-to-landlord disbursement | CaseWorker |
| GET | `/applications/{id}/disbursements` | List an application's disbursements | ProgramAdmin, CaseWorker, Landlord, Tenant |
| GET | `/disbursements/{id}` | Fetch a disbursement | ProgramAdmin, CaseWorker, Landlord |
| POST | `/disbursements/{id}/send` | Mark the payment sent | CaseWorker |
| POST | `/disbursements/{id}/clear` | Mark the payment cleared | ProgramAdmin |
| POST | `/disbursements/{id}/fail` | Mark a sent payment failed | ProgramAdmin |
| POST | `/disbursements/{id}/retry` | Retry a failed payment | CaseWorker |
| POST | `/applications/{id}/recertifications` | Open a recertification | CaseWorker |
| GET | `/applications/{id}/recertifications` | List an application's recertifications | ProgramAdmin, CaseWorker, Tenant |
| POST | `/recertifications/{id}/decide` | Approve or deny a recertification | CaseWorker |
| POST | `/recapture-cases` | Open a recapture case | FraudInvestigator |
| GET | `/recapture-cases/{id}` | Fetch a recapture case | ProgramAdmin, CaseWorker, FraudInvestigator |
| GET | `/recapture-cases` | List recapture cases (filters) | ProgramAdmin, CaseWorker, FraudInvestigator |
| POST | `/recapture-cases/{id}/substantiate` | Substantiate the case | FraudInvestigator |
| POST | `/recapture-cases/{id}/recover` | Recover funds; trigger the cascade | FraudInvestigator |
| POST | `/recapture-cases/{id}/dismiss` | Dismiss the case | FraudInvestigator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_TENANT_NOT_FOUND` | 404 |
| `ERR_LANDLORD_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_LEDGER_NOT_FOUND` | 404 |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 |
| `ERR_RECERT_NOT_FOUND` | 404 |
| `ERR_RECAPTURE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SECTION_INCOMPLETE` | 409 |
| `ERR_UNIT_LANDLORD_MISMATCH` | 422 |
| `ERR_W9_NOT_VERIFIED` | 422 |
| `ERR_LEDGER_NOT_VERIFIED` | 422 |
| `ERR_FRAUD_HOLD` | 409 |
| `ERR_HARDSHIP_NOT_ATTESTED` | 422 |
| `ERR_INCOME_INELIGIBLE` | 422 |
| `ERR_DUPLICATE_BENEFIT` | 409 |
| `ERR_PROSPECTIVE_OVERLAP` | 409 |
| `ERR_MONTHS_CAP_EXCEEDED` | 422 |
| `ERR_FUNDING_EXHAUSTED` | 402 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_AWARD_EXCEEDED` | 422 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_LEDGER_ALREADY_EXISTS` | 409 |
