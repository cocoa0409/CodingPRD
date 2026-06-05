# Life Insurance Underwriting API — Product Requirements Document

## 1. Introduction

Life insurance underwriting is the disciplined process of deciding whether, and on what terms, a carrier will accept the mortality risk of a proposed insured. It is rarely a single decision; it is a sequence of dependent judgments that must be auditable end to end — an application is taken, a paramedical exam is ordered and performed, medical-history and prescription databases are consulted, a risk class is assigned, an offer is extended at a price, and only then is a policy issued and brought into force. This API models that entire arc as a set of state-driven resources, so that every premium figure, every risk debit, and every lifecycle transition can be reproduced and defended after the fact.

The system serves three operational audiences. Operational administrators stand up the rate products and register the underwriting staff. Underwriters drive an application from intake through a final decision, with a deliberate control built in: the underwriter who orders evidence on a case must never be the one who signs off on its approval. Policy owners — the insureds themselves once a policy exists — pay premiums, name beneficiaries, borrow against accumulated cash value, and rescue a lapsed contract through reinstatement. Two recurring tensions shape the rules throughout: a *provisional* price quoted from self-declared facts versus a *final* price grounded in examined evidence, and a contract whose funding lifecycle (in force, in grace, lapsed) advances on one clock while its contestability standing advances on an entirely separate one.

Because money flows and time-based standing must reconcile to the cent and to the day, the specification below fixes precise contracts for response shape, pagination, concurrency, and rounding, then narrates the underwriting and policy-servicing workflows in business terms. Implementers should treat the workflow narratives in Section 3 as the authoritative source for which fields each operation consumes and which downstream records it mutates.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers that together establish the caller's operational context: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `Admin`, `Underwriter`, and `PolicyOwner`. A request that omits `X-User-Role`, carries a value outside this set, or omits `X-User-ID` where the role requires an identity is rejected with `ERR_UNAUTHENTICATED`. A syntactically valid request whose role is not permitted to invoke the targeted operation is rejected with `ERR_UNAUTHORIZED`.

The three roles bind to identity differently, and the binding governs ownership checks. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. When `X-User-Role` is `Underwriter`, `X-User-ID` is the `id` of the acting `Underwriter` row; any ownership or segregation check that references an underwriter — most importantly the comparison against an application's recorded ordering underwriter — compares that stored foreign key to `X-User-ID`. When `X-User-Role` is `PolicyOwner`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on a policy and its sub-resources trace the policy back through its originating application to that applicant and compare the resulting applicant `id` to `X-User-ID`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not be less than 1, and may not exceed 100. The `offset` parameter skips a number of leading items and defaults to 0 and may not be negative. A `limit` or `offset` that is non-integer or outside its permitted range is rejected with `ERR_INVALID_REQUEST`. Unless a specific endpoint says otherwise, list results are ordered by the resource's `created_at` timestamp in ascending order, with ties between rows sharing a `created_at` instant broken by their server-assigned creation order. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties

Most resources carry a uniform set of system-managed fields. Every resource has an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Resources that can be modified after creation additionally carry an `updated_at` timestamp, refreshed to the current instant on every mutation, and a `version` integer that begins at 1 and increments by one with each mutation.

Two entities are append-only audit records and therefore carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field: the `MIBCheck` and the `CashValueEntry`. The `PremiumPayment` is likewise a non-versioned record: once a payment is recorded it is never mutated, so it too exposes only `id` and `created_at` without `updated_at` or `version`. All other resources — `Product`, `Applicant`, `Underwriter`, `Application`, `ParamedExam`, `RiskAssessment`, `Policy`, `Beneficiary`, and `PolicyLoan` — carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Nested Resource Retrieval and Reference Integrity

Many paths address a resource through a parent, for example a list of paramed exams under an application or a list of premium payments under a policy. The server validates path identifiers strictly left to right, rejecting the request with `ERR_NOT_FOUND` at the first segment that names a non-existent resource before it considers any segment to its right. Separately, when a create body carries a foreign key — `applicant_id`, `product_id`, `application_id`, or `policy_id` — the referenced row must exist; a dangling reference is rejected with `ERR_REFERENCE_NOT_FOUND`. Both conditions return HTTP 404, but they are distinct: path existence is `ERR_NOT_FOUND`, body-reference existence is `ERR_REFERENCE_NOT_FOUND`.

### 2.6. Monetary Representation, Debits, and Rounding

All monetary quantities in the system are integer counts of cents — face amounts, premiums, cash values, loan principals, and accrual increments alike. There are no fractional cents and no floating-point money. Where a calculation requires a multiplication or a rate application that would otherwise produce a fraction, the result is rounded half up to the nearest whole cent. The premium engine performs this rounding once per multiplication step in a pinned order rather than once at the end, so that intermediate results are themselves whole cents (see Section 3 for the exact sequence). Risk debits, blood-pressure points, and table ratings are plain integers and are never rounded. Body-mass-index values used internally during risk classification are computed to three decimal places using integer milli-unit arithmetic, then compared against fixed band edges; the BMI value itself is not persisted.

### 2.7. The Two Independent Policy Clocks

A `Policy` advances along two dimensions that move independently of one another and must never be conflated. The first is its funding lifecycle, recorded in `lifecycle_status`, which walks among `IN_FORCE`, `GRACE`, `LAPSED`, `REINSTATED`, and `TERMINATED`. The second is its contestability standing, recorded in `contestability_status`, which holds either `CONTESTABLE` or `INCONTESTABLE`. A single mutation may touch either dimension, both, or neither, and the two are stored on the same policy row. Whenever any reconciliation changes a derived or status field on a policy, that change is a mutation: it refreshes the policy's `updated_at` and increments its `version`.

Several of these transitions are observed lazily rather than pushed. The server maintains a logical clock; an administrator may advance it. The funding lifecycle and the contestability standing are not eagerly recomputed when the clock moves — instead, the next read or write that touches a policy reconciles its status against the current clock. A policy fetch therefore always reflects the correct state for the current instant even though no client explicitly requested the transition.

### 2.8. Derived-Value Reconciliation Across the Cash-Value Ledger

A policy's cash value is the running product of an append-only ledger of `CashValueEntry` rows rather than a free-standing number. The gross cash value, `gross_cash_value_cents`, is always the exact integer sum of every `amount_cents` across the policy's cash-value entries, where each entry's `reason` — one of `PREMIUM_ACCRUAL`, `LAPSE_FORFEIT`, or `LOAN_REVERSAL` — distinguishes a positive premium accrual from a negative forfeiture or reversal. In practice the ledger only ever receives `PREMIUM_ACCRUAL` entries (on issue and on each accepted premium payment) and `LAPSE_FORFEIT` entries (on lapse); `LOAN_REVERSAL` is a defined reason that is never instantiated, because drawing or repaying a loan does not append a cash-value entry — it adjusts `outstanding_loan_principal_cents` directly and leaves `gross_cash_value_cents` unchanged. The net cash value, `net_cash_value_cents`, is the gross less the total principal of currently active loans, never allowed to fall below zero. The field `outstanding_loan_principal_cents` is itself the sum of `principal_cents` across all of the policy's loans whose `status` is `ACTIVE`. Any event that moves gross cash value or outstanding principal — an accrual, a loan draw, a loan repayment, or a lapse forfeiture — triggers an immediate reconciliation that recomputes `outstanding_loan_principal_cents`, then recomputes `net_cash_value_cents` as the gross minus that outstanding principal with a floor of zero, and bumps the policy's `version` and `updated_at`.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of their parent, and both express the guard through a mandatory version field rather than an optional one.

Drawing a policy loan requires the request to carry `expected_policy_version`, which must equal the target policy's current `version`. If a prior writer has advanced the policy's version since the client last read it — for instance, by drawing another loan that legitimately reduced the available loan value — the create is rejected with `ERR_STALE_POLICY_VERSION` at HTTP 412, because the client's notion of available loan value is no longer trustworthy. Approving an application requires the request to carry `expected_application_version`, which must equal the application's current `version`; if another underwriter has, for example, re-ordered a paramed exam and thereby moved the case back to evidence-gathering and refreshed its risk assessment, the application's version will have advanced and the approval is rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412. No other endpoint accepts a version field, and the framing here is strictly about a version that has moved on since it was last observed — not about requests arriving together in time.

### 2.10. Segregation of Underwriting Duties

A core compliance control separates the gathering of evidence from the rendering of a verdict. When an underwriter orders a paramed exam on an application, the system pins that underwriter's `id` onto the application as its ordering underwriter. At the moment of any final disposition rendered out of review — approval, postponement, or decline — the acting underwriter's `id` must differ from that pinned ordering underwriter. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403. This is why the ordering underwriter is captured and held across the life of the case rather than recomputed at decision time.

### 2.11. Validation Ordering

When several checks could fault a single request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then authorization against the role matrix (`ERR_UNAUTHORIZED`), then existence of every path-referenced resource left to right (`ERR_NOT_FOUND`), then existence of every body foreign key (`ERR_REFERENCE_NOT_FOUND`), then well-formedness of the body — required fields present, correct types, enum values within their declared sets, and integers inside their declared ranges (`ERR_INVALID_REQUEST`), then uniqueness on create where applicable (`ERR_DUPLICATE_VALUE`), then whether the requested transition is even defined from the resource's current state (`ERR_INVALID_STATE`). Domain rules follow this preamble. For begin-review, evidence completeness is checked (`ERR_EVIDENCE_INCOMPLETE`). For the completion of a paramed exam, the exam-window overlap check runs (`ERR_EXAM_WINDOW_OVERLAP`). For the decisions rendered out of review, segregation of duties is enforced (`ERR_SEGREGATION_OF_DUTIES`) and then the uninsurable-risk gate (`ERR_UNINSURABLE_RISK`). For issue, offer expiry is enforced (`ERR_OFFER_EXPIRED`). For reinstatement, the reinstatement-window check runs (`ERR_REINSTATEMENT_WINDOW_CLOSED`). For premium payment, the exact-amount check (`ERR_PREMIUM_AMOUNT_MISMATCH`) precedes the coverage-overlap check (`ERR_COVERAGE_PERIOD_OVERLAP`). Beneficiary share validity (`ERR_BENEFICIARY_SHARE_INVALID`), loan-value sufficiency (`ERR_LOAN_EXCEEDS_VALUE`), and product face-amount ceiling (`ERR_FACE_EXCEEDS_PRODUCT_MAX`) are enforced within their respective operations. The optimistic-concurrency version check is the last gate before a guarded mutation commits.

## 3. Business Logic & Workflows

### 3.1. Configuring Products and Staff

Before any application can exist, an `Admin` configures the rate products and registers the people who will work the cases. A `Product` is created with a human-readable `code` that must be unique across all products and non-empty; a duplicate code is rejected with `ERR_DUPLICATE_VALUE`. Pricing and policy behavior are governed by a cluster of product parameters. The `base_annual_rate_per_thousand_cents` is the base annual premium, in cents, charged per one thousand dollars of face amount at the `STANDARD` risk class before any tobacco or class adjustment, and it must be at least 1. The `max_face_amount_cents` is the largest death benefit the product will issue, in cents, and must be at least one hundred thousand (that is, at least one thousand dollars expressed in cents). The `cash_value_accrual_rate_bps` is the annual cash-value accrual rate in basis points and must be between 0 and 10000 inclusive.

Several product fields have defaults applied when omitted on creation. The `contestability_months` field is the length of the contestability window in whole months measured from issue and defaults to 24, with a minimum of 1. The `grace_period_days` field is the number of days after a missed due date before the contract lapses and defaults to 31, with a minimum of 1. The `max_loan_to_cash_value_pct` field is the largest loan principal expressible as a whole-number percentage of net cash value, defaulting to 90 and constrained between 1 and 100 inclusive. The `exam_validity_days` field is how many days a paramed exam remains valid from its exam date, defaulting to 180 with a minimum of 1.

An `Underwriter` is registered with a `name` and a `license_id`; the license identifier must be unique across underwriters and non-empty, and a collision is rejected with `ERR_DUPLICATE_VALUE`. An `Applicant` — the proposed insured — is created with a legal `full_name`, a `date_of_birth` given as an ISO 8601 date in the past, a `sex` that must be either `MALE` or `FEMALE`, a `tobacco_use` boolean recording any tobacco use in the prior twelve months, and an `email` that must be non-empty and unique across applicants, with duplicates rejected as `ERR_DUPLICATE_VALUE`. Both administrators and underwriters may create applicants.

### 3.2. Opening and Submitting an Application

An `Underwriter` opens a case by creating an `Application`, which references an applicant via `applicant_id` and a product via `product_id` and records the `requested_face_amount_cents`, the death benefit sought, which must be at least one hundred thousand cents. A new application begins in `DRAFT`. At create time the requested face amount is checked against the chosen product's ceiling; a request exceeding `max_face_amount_cents` is rejected with `ERR_FACE_EXCEEDS_PRODUCT_MAX`.

Submitting the application advances it from `DRAFT` to `SUBMITTED`, but only while it is in `DRAFT` and only when the referenced applicant and product both exist and the requested face amount does not exceed the product's maximum — a face overage at submit is again `ERR_FACE_EXCEEDS_PRODUCT_MAX`. Submission computes a provisional annual premium from the facts declared so far and writes it to `provisional_annual_premium_cents`, which is null until this point. The provisional calculation proceeds in a pinned order. First, the number of thousands of coverage is the requested face amount in cents divided by one hundred thousand using integer division (discarding any remainder). Second, a base figure is that thousands count multiplied by the product's `base_annual_rate_per_thousand_cents`. Third, a tobacco multiplier of 1500 milli-units applies when the applicant uses tobacco and 1000 milli-units when they do not. Fourth, the class multiplier for the provisional variant is fixed at 1000 milli-units, because no exam yet exists and the case is priced as if `STANDARD`. The combination then runs multiplicatively: an after-tobacco figure is the base multiplied by the tobacco multiplier divided by 1000 and rounded half up to a whole cent, and the provisional premium is that after-tobacco figure multiplied by the class multiplier divided by 1000 and rounded half up to a whole cent. Submission also increments the application's `version`.

### 3.3. Ordering Evidence: Paramed Exams and MIB/Rx Checks

From `SUBMITTED`, an underwriter orders the paramedical exam, moving the application to `EXAM_PENDING`. This ordering action does two consequential things beyond the state change: it records the acting underwriter's `id` into the application's `ordering_underwriter_id`, pinning the subject of the later segregation check, and it increments the application's `version`. The same ordering action is also available from `UNDER_REVIEW` as a revision loop — when a reviewer needs fresh evidence, ordering a new exam falls the case back from `UNDER_REVIEW` to `EXAM_PENDING`, re-pins the ordering underwriter, and bumps the version. The application also tracks a `deciding_underwriter_id`, which remains null until a decision transition fires and then records whoever rendered that decision.

A `ParamedExam` is attached to an application while it sits in `EXAM_PENDING`, created in `ORDERED` status. The exam captures `height_inches` as a whole number between 48 and 84 inclusive, `weight_pounds` as a whole number between 60 and 500 inclusive, `systolic_bp` in millimeters of mercury between 70 and 260 inclusive, and an `exam_date` given as a valid ISO 8601 date. The exam date is the inclusive start of a validity window that runs forward by the product's `exam_validity_days` and ends exclusively, so the window is closed at its start and open at its end. An ordered exam may be completed, advancing `ORDERED` to `COMPLETED`, provided height, weight, systolic pressure, and exam date are all present and the exam-window overlap test passes. That test treats two exams' validity windows as overlapping exactly when each window's start falls strictly before the other window's exclusive end; two windows that merely touch end-to-start do not overlap, so adjacency is permitted. If the exam being completed has a validity window that overlaps the window of any already-`COMPLETED` exam on the same application, completion is rejected with `ERR_EXAM_WINDOW_OVERLAP`. Alternatively, an ordered exam may be abandoned, moving `ORDERED` to `CANCELLED`. Either transition increments the exam's `version`.

In parallel, an underwriter records one or more medical-history-and-prescription checks against the application. An `MIBCheck` carries a `mib_hit` boolean indicating whether the Medical Information Bureau returned a coded impairment hit and an `rx_flag_count` giving the number of flagged prescriptions returned by the prescription database, which must be zero or greater. The check's `result` is computed at creation: it is `CLEAR` when there is no MIB hit and the flagged-prescription count is exactly zero, and `FLAGGED` otherwise. This disposition later governs the postpone/decline gate at review.

### 3.4. Review and Risk Classification

Once at least one exam on the application has reached `COMPLETED` and at least one MIB check exists, an underwriter begins review, advancing `EXAM_PENDING` to `UNDER_REVIEW`. Beginning review without both a `COMPLETED` exam and at least one MIB check present is rejected with `ERR_EVIDENCE_INCOMPLETE`. A postponed case may also re-enter review, advancing `POSTPONED` to `UNDER_REVIEW`, which requires only that at least one `COMPLETED` exam exist on the application. Either path runs the risk classification and creates or refreshes the application's `RiskAssessment`, and increments the application's `version`.

Risk classification reads the single `COMPLETED` paramed exam with the most recent `created_at` for the application. From that exam it derives a body-mass index as the measured weight in pounds multiplied by 703000, divided by the square of the height in inches, rounded half up, and then divided by 1000 to yield a value with three decimal places. The BMI maps to build debits by band, with each band's upper edge inclusive: a BMI at or below 27.5 contributes 0 debits; a BMI above 27.5 and at or below 32.0 contributes 50; a BMI above 32.0 and at or below 37.0 contributes 100; and a BMI above 37.0 contributes 200. Systolic pressure maps to its own debits, again with inclusive upper edges: at or below 135 contributes 0; above 135 and at or below 150 contributes 50; above 150 contributes 100. The two band contributions sum into `build_debits`.

Impairment debits are then layered on. A tobacco-using applicant adds 50 debits, and if any MIB check on the application has a `FLAGGED` result, a further 75 debits are added. The sum of build debits and these impairment debits is `total_debits`. Where neither tobacco use nor any flagged check applies, the total equals the build debits alone; where either or both apply, the corresponding 50 and 75 are added on top, which can push an otherwise modest build into a higher table rating. The total then determines `risk_class` and the numeric `table_rating`, with each threshold lower-bound inclusive: a total below 50 yields `PREFERRED` with a table rating of 0; a total of at least 50 but below 100 yields `STANDARD`, also with a table rating of 0; a total of 100 or more yields a `TABLE_N` class, where N is computed as the integer floor of the quantity (total debits minus 100) divided by 50, plus 1, and N is capped at 8. The assessment's `table_rating` equals that N for a table class, and the `risk_class` is the matching member of the ladder `TABLE_1`, `TABLE_2`, `TABLE_3`, `TABLE_4`, `TABLE_5`, `TABLE_6`, `TABLE_7`, `TABLE_8`. The assessment also carries a `finalized` flag, which is false until an approval locks it.

### 3.5. The Underwriting Decision

From `UNDER_REVIEW`, an underwriter renders one of three dispositions, and each records the acting underwriter into `deciding_underwriter_id` and increments the application's `version`. All three require that the acting underwriter differ from the pinned ordering underwriter, failing otherwise with `ERR_SEGREGATION_OF_DUTIES`.

Approval advances `UNDER_REVIEW` to `APPROVED_OFFER`. It is the most heavily guarded transition. Beyond segregation of duties, it requires that a risk assessment exist whose `risk_class` is neither `TABLE_7` nor `TABLE_8`, that every MIB check on the application carries a `CLEAR` result, and that the supplied `expected_application_version` match the application's current `version`. An assessed class of `TABLE_7` or `TABLE_8`, or the presence of any `FLAGGED` MIB check, blocks approval as `ERR_UNINSURABLE_RISK`; a version that no longer matches yields `ERR_STALE_APPLICATION_VERSION`. On success, approval computes the final annual premium and writes `final_annual_premium_cents`, which was null until now; it sets the assessment's `finalized` flag to true, locking that assessment so it can no longer change; it records `deciding_underwriter_id`; and it sets `offer_expires_at` to thirty days after the current clock instant. The final premium follows the same pinned multiply-and-round sequence as the provisional one — thousands of coverage, base figure, tobacco multiplier of 1500 or 1000 milli-units, after-tobacco rounded half up — but its class multiplier is derived from the finalized assessment rather than assumed: `PREFERRED` uses 850 milli-units, `STANDARD` uses 1000 milli-units, and a `TABLE_N` class uses 1000 plus N times 250 milli-units, where N is the table rating (ratings 1 through 6 are the ones reachable at approval, since 7 and 8 are never approved). The premium is the after-tobacco figure multiplied by this class multiplier divided by 1000, rounded half up to a whole cent. Consequently the final premium differs from the provisional whenever the assessed class is anything other than `STANDARD`.

Postponement advances `UNDER_REVIEW` to `POSTPONED`, and decline advances `UNDER_REVIEW` to `DECLINED`; both require only that the case be under review and that segregation of duties hold. A decline is also available directly from `SUBMITTED`, advancing `SUBMITTED` to `DECLINED` without a segregation check, since no ordering underwriter need have been pinned at that early stage; this early decline still records the acting underwriter into `deciding_underwriter_id` and increments the application's `version`, exactly as the under-review dispositions do. `DECLINED` is terminal.

### 3.6. Issuing the Policy

An approved offer is good for a bounded window. Issuing advances `APPROVED_OFFER` to `ISSUED`, but only while the offer has not expired — the current clock instant must be at or before `offer_expires_at` — and only when the supplied `expected_application_version` matches the application's current `version`. An attempt to issue after the offer instant has passed is rejected with `ERR_OFFER_EXPIRED`. Expiry itself is observed lazily: once the clock moves past `offer_expires_at`, any read or issue attempt treats the offer as `EXPIRED`, and an application that has lapsed in this way carries `EXPIRED` status; `EXPIRED` and `ISSUED` are both terminal, alongside `DECLINED`.

Issuing is the origin of a cascade. It creates exactly one `Policy` for the application, in `lifecycle_status` `IN_FORCE` and `contestability_status` `CONTESTABLE`. The new policy copies its `face_amount_cents` from the application's requested face amount and its `annual_premium_cents` from the application's final premium. Its `issue_date` is set to the current clock's date — the moment from which the contestability clock runs — and its `next_premium_due_date` is set to one year after issue. Its `cumulative_premium_paid_cents` is seeded at issue to exactly one annual premium (the policy's `annual_premium_cents`), since the first year's coverage is funded by the act of issuing. The act of issuing also lays down the first cash-value accrual: a `CashValueEntry` with reason `PREMIUM_ACCRUAL` is created for the first year — its `amount_cents` being that seeded cumulative premium multiplied by the product's `cash_value_accrual_rate_bps`, divided by ten thousand, rounded half up per the Section 3.7 formula — which recomputes `gross_cash_value_cents` and reconciles `net_cash_value_cents` as described in Section 2.8. Issuing increments the application's `version`.

### 3.7. Keeping a Policy In Force: Premiums and Cash Value

A `PolicyOwner` keeps the contract alive by paying the annual premium. A `PremiumPayment` carries an `amount_cents` that must be at least 1 and, to be accepted, must exactly equal the policy's `annual_premium_cents`; any other amount is rejected with `ERR_PREMIUM_AMOUNT_MISMATCH`. Each payment funds a half-open coverage interval. The interval's start, `coverage_period_start`, may be supplied explicitly to pre-pay a future anniversary; when omitted it defaults to the policy's current `next_premium_due_date`, which is the on-cycle case. The interval's end, `coverage_period_end`, is one year after its start and is exclusive. The system also records `paid_at`, the server-clock instant the payment was taken, and `applied_to_due_date`, the due date this payment satisfied, captured before the cycle advances. Two payments' coverage intervals are considered overlapping exactly when one interval's start falls strictly before the other's end and that other's start falls strictly before the first's end; because the intervals are half-open, a payment whose coverage starts exactly where a prior payment's coverage ends does not overlap and is allowed. A payment whose coverage interval overlaps an existing payment's interval on the same policy — for instance, an attempt to re-fund an already-funded anniversary — is rejected with `ERR_COVERAGE_PERIOD_OVERLAP`.

A payment accepted while the policy is `IN_FORCE` keeps it `IN_FORCE`; a payment accepted while it is in `GRACE` restores it to `IN_FORCE`, provided the current clock date is at or before the next due date plus the product's grace-period days; a payment attempt once that grace deadline has passed is rejected with `ERR_INVALID_STATE`. On acceptance the payment is recorded; the policy's `next_premium_due_date` advances by one year only when the payment was on-cycle (its coverage start equals the current next due date); the amount is added to `cumulative_premium_paid_cents`; and a cash-value accrual fires. The accrual increment is the running cumulative premium paid — taken after this payment has been added — multiplied by the product's `cash_value_accrual_rate_bps`, divided by ten thousand, and rounded half up to a whole cent. A new `CashValueEntry` with reason `PREMIUM_ACCRUAL` for that increment is appended, after which `gross_cash_value_cents` is recomputed as the exact sum of all the policy's entry amounts and `net_cash_value_cents` is reconciled. The payment increments the policy's `version`.

### 3.8. Grace, Lapse, Reinstatement, and Termination

When the clock passes a policy's `next_premium_due_date` while it is `IN_FORCE`, the policy lazily enters `GRACE` on the next read or payment attempt — grace begins the day after the due date — incrementing the policy's `version`. If the clock then passes the due date plus the product's grace-period days while the policy is still in `GRACE`, the policy lazily lapses, advancing `GRACE` to `LAPSED`. Lapse forfeits accumulated cash value: a `CashValueEntry` with reason `LAPSE_FORFEIT` is appended whose `amount_cents` equals the negative of the current gross cash value, which drives the gross back to zero through the standard recompute-and-reconcile cascade, and the policy's `version` increments.

A lapsed contract may be rescued. Reinstatement advances `LAPSED` to `REINSTATED`, but only while the current clock date is at or before three years after the issue date — the reinstatement window — failing otherwise with `ERR_REINSTATEMENT_WINDOW_CLOSED`. The request must also make the policy whole on missed premiums by supplying `back_premium_count`, the whole number of overdue annual premiums measured from the applied due date through the current clock. A count that does not cover every overdue annual premium is rejected with `ERR_BACK_PREMIUM_INSUFFICIENT`. On success, exactly `back_premium_count` back premiums are recorded as payments, each of `amount_cents` equal to the policy's `annual_premium_cents` and each covering one consecutive annual interval beginning at the current applied due date and stepping forward a year at a time (the first carries `applied_to_due_date` equal to that applied due date) — each subject to the same coverage-interval overlap rule, so an overlapping reinstatement period is likewise rejected with `ERR_COVERAGE_PERIOD_OVERLAP`. The `next_premium_due_date` then advances by `back_premium_count` years from the applied due date (the first future anniversary when the count exactly covers the overdue premiums), the paid amounts are added to `cumulative_premium_paid_cents`, and cash value accrues for each reinstated premium through the usual entry-and-reconcile cascade. Crucially, reinstatement resets contestability: `contestability_status` is set back to `CONTESTABLE` and a fresh contestability window begins from the reinstatement date, distinct from the original issue clock. Reinstatement increments the policy's `version`. Should the clock instead pass three years after issue while the policy remains `LAPSED`, the policy lazily moves `LAPSED` to `TERMINATED`, a terminal state, incrementing its `version`.

Independently of all the above, the contestability dimension flips once its window elapses. When the clock reaches at least the issue date plus the product's `contestability_months` while the policy is still `CONTESTABLE`, the next read lazily sets `contestability_status` to `INCONTESTABLE` and increments the policy's `version`. This evolution is entirely separate from the funding lifecycle; a reinstated policy, as noted, restarts this window afresh from its reinstatement date.

### 3.9. Beneficiaries, Loans, and Repayment

A `PolicyOwner` names beneficiaries on the policy. A `Beneficiary` carries a non-empty `full_name`, a `designation` that is either `PRIMARY` or `CONTINGENT`, and a `share_pct` whole-number share between 1 and 100 inclusive. Shares are validated per designation tier: after adding a beneficiary, the sum of `share_pct` across the `PRIMARY` tier must equal 100, and if any contingent beneficiary exists, the `CONTINGENT` tier's shares must likewise sum to 100; otherwise the operation is rejected with `ERR_BENEFICIARY_SHARE_INVALID`. Contingent beneficiaries take a benefit only when no primary remains. Removing a beneficiary applies the same tier-sum rule afterward: the remaining shares in the affected tier must still total 100, unless that tier has become empty, and a removal that would leave a tier summing to something other than 100 is rejected with `ERR_BENEFICIARY_SHARE_INVALID`.

A `PolicyOwner` may borrow against accumulated value by drawing a `PolicyLoan`, which records a `principal_cents` of at least 1 and begins in `ACTIVE` status. Loan creation is the optimistic-concurrency-guarded operation of Section 2.9: the request carries `expected_policy_version`, and a mismatch with the policy's current `version` is rejected with `ERR_STALE_POLICY_VERSION`. The principal is also capped by available loan value. The cap is the gross cash value multiplied by the product's `max_loan_to_cash_value_pct`, divided by 100, rounded half up to a whole cent; the amount actually available is that cap less the already-outstanding loan principal, never below zero. A requested principal that exceeds the available amount is rejected with `ERR_LOAN_EXCEEDS_VALUE`, while a principal exactly equal to the available amount is permitted. Drawing a loan adds its principal to `outstanding_loan_principal_cents`, reconciles `net_cash_value_cents`, and increments the policy's `version`.

Repaying a loan advances it from `ACTIVE` to `REPAID`. Repayment is a compensating action: it subtracts the loan's principal from the policy's `outstanding_loan_principal_cents`, reconciles `net_cash_value_cents` back toward its pre-loan level, increments the policy's `version`, and increments the loan's own `version`.

### 3.10. The Test-Driving Clock

Because so much of the policy lifecycle turns on the passage of time, the system exposes an administrator-only capability to set the server's current UTC instant by supplying a target instant as `to_iso8601`. Advancing the clock does not itself push any transition; rather, it changes what subsequent reads and writes observe. After the clock moves, the lazy transitions described throughout Section 3 — offer expiry, entry into grace, lapse, termination, and the contestability flip — surface on the next operation that touches the affected resource.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource, including state transitions and list or fetch reads, return `200 OK`. Request bodies, response payloads, and side effects for each operation are described in the Section 3 narratives rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a product (rate table and policy parameters) | Admin |
| GET | `/products/{id}` | Fetch a product | Admin, Underwriter |
| POST | `/underwriters` | Register an underwriter | Admin |
| GET | `/underwriters/{id}` | Fetch an underwriter | Admin, Underwriter |
| POST | `/applicants` | Create an applicant (proposed insured) | Admin, Underwriter |
| GET | `/applicants/{id}` | Fetch an applicant | Admin, Underwriter |
| POST | `/applications` | Create a DRAFT application | Underwriter |
| GET | `/applications/{id}` | Fetch an application (reflects offer expiry on read) | Admin, Underwriter |
| GET | `/applications` | List applications, optionally filtered | Admin, Underwriter |
| POST | `/applications/{id}/submit` | Submit an application; computes provisional premium | Underwriter |
| POST | `/applications/{id}/order-exam` | Order a paramed exam; pins the ordering underwriter | Underwriter |
| POST | `/applications/{id}/begin-review` | Begin review; runs risk classification | Underwriter |
| POST | `/applications/{id}/approve` | Approve and extend an offer; computes final premium | Underwriter |
| POST | `/applications/{id}/postpone` | Postpone the application | Underwriter |
| POST | `/applications/{id}/decline` | Decline the application | Underwriter |
| POST | `/applications/{id}/issue` | Issue the policy from an approved offer | Underwriter |
| POST | `/applications/{id}/paramed-exams` | Attach a paramed exam to an application | Underwriter |
| GET | `/applications/{id}/paramed-exams` | List paramed exams for an application | Admin, Underwriter |
| GET | `/paramed-exams/{id}` | Fetch a paramed exam | Admin, Underwriter |
| POST | `/paramed-exams/{id}/complete` | Complete a paramed exam | Underwriter |
| POST | `/paramed-exams/{id}/cancel` | Cancel a paramed exam | Underwriter |
| POST | `/applications/{id}/mib-checks` | Record an MIB/Rx check for an application | Underwriter |
| GET | `/applications/{id}/mib-checks` | List MIB/Rx checks for an application | Admin, Underwriter |
| GET | `/applications/{id}/risk-assessment` | List the risk assessment(s) for an application | Admin, Underwriter |
| GET | `/policies/{id}` | Fetch a policy (reflects lazy lifecycle and contestability transitions) | Admin, Underwriter, PolicyOwner |
| GET | `/applications/{id}/policies` | List the policy(ies) for an application | Admin, Underwriter |
| POST | `/policies/{id}/premium-payments` | Record an annual premium payment | PolicyOwner |
| GET | `/policies/{id}/premium-payments` | List premium payments for a policy | Admin, Underwriter, PolicyOwner |
| POST | `/policies/{id}/reinstate` | Reinstate a lapsed policy | PolicyOwner |
| POST | `/policies/{id}/beneficiaries` | Add a beneficiary to a policy | PolicyOwner |
| GET | `/policies/{id}/beneficiaries` | List beneficiaries for a policy | Admin, Underwriter, PolicyOwner |
| DELETE | `/beneficiaries/{id}` | Remove a beneficiary | PolicyOwner |
| POST | `/policies/{id}/policy-loans` | Draw a policy loan against net cash value | PolicyOwner |
| GET | `/policies/{id}/policy-loans` | List policy loans for a policy | Admin, Underwriter, PolicyOwner |
| POST | `/policy-loans/{id}/repay` | Repay a policy loan | PolicyOwner |
| GET | `/policies/{id}/cash-value-entries` | List cash-value ledger entries for a policy | Admin, Underwriter, PolicyOwner |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant (test driving) | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_VALUE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EVIDENCE_INCOMPLETE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_UNINSURABLE_RISK` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_REINSTATEMENT_WINDOW_CLOSED` | 409 |
| `ERR_PREMIUM_AMOUNT_MISMATCH` | 422 |
| `ERR_BENEFICIARY_SHARE_INVALID` | 422 |
| `ERR_LOAN_EXCEEDS_VALUE` | 409 |
| `ERR_FACE_EXCEEDS_PRODUCT_MAX` | 409 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_BACK_PREMIUM_INSUFFICIENT` | 422 |
| `ERR_EXAM_WINDOW_OVERLAP` | 409 |
| `ERR_COVERAGE_PERIOD_OVERLAP` | 409 |
