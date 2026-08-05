# Transient-Occupancy Hotel-Tax API — Product Requirements Document

## 1. Introduction

Local jurisdictions levy a Transient-Occupancy Tax (TOT), commonly called a hotel or lodging tax, on the short-term rental of rooms and lodging units. Administering that tax is a reconciliation problem at heart: lodging operators register for a certificate, file periodic returns declaring their gross receipts, claim exemptions for long-term and government guests, and remit what they owe — while the jurisdiction (and its online-travel-agency partners) must keep an accurate running account of every dollar owed, paid, penalized, abated, or refunded. This API is the system of record for that entire relationship.

The design goal is a single, drift-free money trail. Every taxable event, payment, penalty, assessment, abatement, and refund posts an immutable entry to an append-only ledger, and an operator's account balance is always exactly the sum of that ledger — never a separately maintained number. On top of this ledger sit the compliance workflows: monthly and quarterly filing, exemption verification, OTA collection agreements, field audits that can propose deficiency assessments, taxpayer appeals with negotiation rounds, delinquency-driven liens, and interest-bearing refunds. Because the same underlying balance drives an operator's status (active, delinquent, suspended, revoked, or closed), state and money are tightly coupled and must reconcile immediately on every mutation.

This document specifies the complete contract: the global conventions every endpoint obeys (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5). Monetary amounts are handled in whole cents throughout, and time is driven by a controllable logical clock so that due dates, penalty windows, and interest accrual are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `TaxAdmin`, `Operator`, and `Auditor`.

- **`TaxAdmin`** is the jurisdiction administrator. It configures jurisdictions and OTA platforms, registers and manages operators, verifies and rejects exemptions, clears and reverses remittances, issues assessments, decides appeals, records liens, and approves, denies, and pays refunds. When `X-User-Role` is `TaxAdmin`, `X-User-ID` is an opaque administrator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id` for ownership.
- **`Operator`** is a registered lodging operator. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator` record. Ownership checks on any resource that references an operator compare that resource's `operator_id` (directly, or transitively through its parent chain — a return, exemption, remittance, or appeal ultimately resolves to an owning operator) against `X-User-ID`. An operator acting on a resource it does not own is rejected with `ERR_FORBIDDEN_OWNERSHIP`.
- **`Auditor`** is a tax auditor who opens audits, conducts fieldwork, proposes assessments and their classification, records taxpayer responses, and closes audits with no change. An auditor may never issue an assessment — issuance is reserved to `TaxAdmin` (see the four-eyes rule in Section 3.8). When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque auditor identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

All read (`GET`) endpoints are available to `TaxAdmin`, `Operator`, and `Auditor` alike. Write endpoints are restricted as described in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. In addition, several list endpoints accept optional exact-match filter query parameters applied before pagination: `GET /operators` by `jurisdiction_id` and `status`; `GET /ota-agreements` by `operator_id`, `platform_id`, and `status`; `GET /remittances` by `tax_return_id`, `ota_agreement_id`, and `status`; `GET /refund-claims` by `operator_id`, `tax_return_id`, and `status`; `GET /operators/{id}/returns` by `filing_status` and `settlement_status`; and `GET /operators/{id}/liens` and `GET /returns/{id}/exemptions` by `status`. Any unrecognized query parameter is ignored.

### 2.4. Common Resource Properties and Identifiers

Nearly every resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp (three fractional digits) recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation to the resource.
- `version` — an integer that starts at 1 on creation and increments by exactly 1 on every mutation. It supports optimistic concurrency control.

One entity is deliberately leaner: a **ledger entry**, the atomic money record, is append-only and immutable. Each ledger entry carries only `id` and `created_at`; it has no `updated_at` and no `version`, because a posted entry is never modified. All other resources described in this document carry the full set above.

When a mutation changes derived fields on a resource (for example, recomputing an operator's balance, or a return's tax after an amendment), that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Monetary Precision, Rates, and Rounding

All money is stored and returned as integers in whole cents; there are no fractional cents anywhere in the system. Tax and interest rates are expressed in **basis points**, where one basis point is one ten-thousandth: a rate value is converted to a fraction by dividing by 10,000. For example, a `tax_rate_bps` of 1200 is a tax rate of 12%, an `interest_rate_monthly_bps` of 100 is 1% per month, and a `refund_interest_monthly_bps` of 50 is 0.5% per month.

Wherever a monetary result is produced by multiplying by a rate, the result is rounded to whole cents using the round-half-up convention (a value exactly halfway between two cents rounds up to the larger cent). The precise point at which rounding is applied matters and is specified per calculation in Section 3 — in particular, tax is rounded once per return line and only then summed, never rounded on the grand total.

### 2.6. The Operator Ledger and Account Balance

Each operator has an append-only ledger of money events. Every entry records `operator_id`, an `entry_type` drawn from `TAX_DUE`, `PENALTY`, `INTEREST`, `REMITTANCE`, `REMITTANCE_REVERSAL`, `ASSESSMENT`, `ABATEMENT`, `REFUND`, `ADJUSTMENT`, a signed amount in `amount_signed_cents`, and a `source_ref` pointing at the originating return, remittance, assessment, or refund claim. The sign convention is fixed: amounts the operator owes the jurisdiction (debits) are positive, and payments received (a cleared `REMITTANCE`) are negative. A paid `REFUND`, although it disburses money to the operator, posts a **positive** `amount_signed_cents` equal to `total_refund_cents`, because it consumes the operator's held credit and drives that negative (credit) balance back up toward zero.

An operator's `account_balance_cents` is a computed field defined as the exact sum of `amount_signed_cents` over **all** ledger entries for that operator, with no status filter and no exclusions — the ledger is the single source of truth and the balance never drifts from it. A positive balance means the operator owes the jurisdiction; a negative balance means the operator holds an overpayment credit. Because the ledger is append-only, corrections are made by posting compensating entries (for example a `REMITTANCE_REVERSAL` that offsets a prior `REMITTANCE`, or an `ABATEMENT` that offsets an `ASSESSMENT`), never by editing or deleting an existing entry. This guarantees the invariant that the balance always equals the running total of every entry ever posted.

### 2.7. Cascading Status Reconciliation

Because operator status is a function of money, the server reconciles it automatically — the client never sets it directly. Whenever a ledger entry posts and changes an operator's balance, the server re-evaluates the operator's standing in the same operation:

- An `ACTIVE` operator whose balance becomes strictly greater than zero moves to `DELINQUENT`, but only when there is a concrete delinquency trigger: at least one `FILED` or `AMENDED` return that is past its `due_date` and not yet fully settled (its `settlement_status` is not `PAID`), or an `ISSUED` or `FINAL` assessment.
- A `DELINQUENT` operator whose balance returns to zero or below (after a cleared remittance, a paid refund, or an abatement) moves back to `ACTIVE`, and every `RECORDED` lien for that operator is cascaded to `RELEASED`.

A return also carries a **settlement axis** that is entirely independent of its filing axis and is driven only by cleared remittances (Section 3.6). Reconciling a return's settlement status, an operator's status, and any lien release are all part of the same immediate consistency guarantee: when one mutation changes the balance, every dependent status is brought into alignment before the response is returned, and each affected resource's `updated_at` and `version` are updated accordingly.

### 2.8. Optimistic Concurrency Control on Lien Recording

Recording a lien snapshots the operator's delinquent balance at the moment of recording, so it must act on a fresh view of the operator. The lien-recording request therefore requires a non-optional `expected_operator_version` field carrying the client's last-observed `version` of the target operator. If that value does not match the operator's current `version` — for instance because an intervening cleared remittance posted a partial payment, lowering the balance while the operator remained `DELINQUENT` — the write is rejected with `ERR_STALE_OPERATOR_VERSION` (HTTP 412), even though the delinquency precondition still holds. This prevents the lien from recording a stale amount. Lien recording is the only endpoint that takes a version field; no other endpoint accepts or checks `expected_operator_version`.

### 2.9. Nested Resource Retrieval and Validation Ordering

Many paths address a resource through its parent (for example a lien or a return under an operator, an assessment under an audit, an appeal under an assessment). For any such request, the server validates identifiers left-to-right along the path and rejects the first one that does not resolve with `ERR_NOT_FOUND` before considering anything further to the right or any request body. Only once all path identifiers resolve does the server validate body foreign keys, again with `ERR_NOT_FOUND` if a referenced resource does not exist.

Validation across the whole API follows a fixed priority order so that outcomes are deterministic when several conditions could fail at once: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role permission for the endpoint (`ERR_FORBIDDEN`); (3) existence of referenced resources, path first then body (`ERR_NOT_FOUND`); (4) operator ownership for operator-role write endpoints (`ERR_FORBIDDEN_OWNERSHIP`); (5) the target being in a state that permits the requested transition (`ERR_INVALID_STATE`); (6) the lien optimistic-concurrency check (`ERR_STALE_OPERATOR_VERSION`); (7) temporal non-overlap checks for return periods and OTA agreement coverage (`ERR_PERIOD_OVERLAP` / `ERR_AGREEMENT_OVERLAP`); (8) OTA referential checks — platform registered, agreement active and covering the period (`ERR_PLATFORM_NOT_REGISTERED` / `ERR_OTA_AGREEMENT_INACTIVE`); (9) exemption eligibility (`ERR_EXEMPTION_INELIGIBLE`); (10) the receipts partition guard (`ERR_RECEIPTS_MISMATCH`); (11) fiscal ceilings — remittance not exceeding amount due and refund not exceeding held credit (`ERR_REMITTANCE_EXCEEDS_DUE` / `ERR_REFUND_EXCEEDS_OVERPAYMENT`); (12) the lien threshold (`ERR_BELOW_LIEN_THRESHOLD`); and (13) general well-formedness of the body — required fields present, amounts non-negative, enums valid (`ERR_INVALID_REQUEST`). A check earlier in this order takes precedence over any later one that might also apply to the same request.

### 2.10. The Logical Clock

Time in this system is a controllable logical clock, so that due dates, penalty windows, and interest accrual are deterministic. At startup the clock reads exactly `2026-05-01T00:00:00Z`; before any set call it holds this default and never falls back to wall-clock time. An administrator-only test-driving capability advances the clock to a supplied `to_iso8601` instant; the next mutation after a clock change re-evaluates due dates and penalty windows accordingly. System-stamped timestamps such as a return's `filed_at` and a lien's `recorded_at` are taken from this logical clock at the moment of the event.

## 3. Business Logic & Workflows

### 3.1. Jurisdiction Configuration and Fiscal Constants

A `TaxAdmin` establishes a **jurisdiction**, the taxing authority whose parameters drive every downstream calculation. A jurisdiction is created with a `name` and a `tax_rate_bps` (the TOT rate in basis points). Four further parameters are optional and fall back to statutory defaults when omitted: `interest_rate_monthly_bps`, the monthly delinquency interest rate, defaults to 100 (that is, 1% per month); `refund_interest_monthly_bps`, the monthly interest paid on overpayments being refunded, defaults to 50 (0.5% per month); `lien_threshold_cents`, the delinquent-balance ceiling a lien requires the balance to strictly exceed, defaults to 500000 (five thousand dollars); and `exemption_min_stay_nights`, the minimum consecutive nights that qualify a stay as a long-term exemption, defaults to 30. These constants are read by the tax, penalty, interest, refund, exemption, and lien logic described throughout Section 3.

### 3.2. Operator Registration, Certification, and Account Lifecycle

Registration begins when a `TaxAdmin` creates an **operator** under a jurisdiction, supplying the `jurisdiction_id`, the operator's `legal_name`, and a `filing_frequency` of either `MONTHLY` or `QUARTERLY`. A freshly registered operator starts in `PENDING` status with an `account_balance_cents` of zero and no `certificate_number` (the field is null until activation).

Activation is a `TaxAdmin` action that moves the operator from `PENDING` to `ACTIVE`; it is permitted only while the operator is in `PENDING`, and any other starting state is rejected with `ERR_INVALID_STATE`. On activation the server mints the registration `certificate_number` and sets `status` to `ACTIVE`. From `ACTIVE`, the operator can be moved to `SUSPENDED` (a `TaxAdmin` suspension, which optionally records a `reason`) or, once fully wound down, to `CLOSED`. A `DELINQUENT` operator may also be suspended. A `SUSPENDED` operator can be reinstated by a `TaxAdmin`, returning to `ACTIVE` — and because reinstatement restores an operating status, the server immediately re-evaluates delinquency, so an operator whose balance is still strictly positive with a live delinquency trigger drops straight back to `DELINQUENT`. A `SUSPENDED` operator can instead be revoked, moving to `REVOKED`. The `DELINQUENT` and `ACTIVE` transitions in both directions are system-driven off the ledger, as described in Section 2.7, never set by the client.

Closing an operator is the terminal wind-down and is guarded by two preconditions evaluated together: the operator's `account_balance_cents` must be exactly zero, otherwise the close is rejected with `ERR_OPERATOR_NOT_SETTLED`; and there must be no audit still in progress — that is, no audit in `OPENED`, `FIELDWORK`, `PROPOSED`, or `RESPONSE` status — otherwise it is rejected with `ERR_AUDIT_IN_PROGRESS`. When both hold, the operator moves to `CLOSED`, which is terminal.

An operator owns a set of **properties**, the individual listings whose receipts it reports. A property is created (by a `TaxAdmin`, or by the owning operator) with the `operator_id`, a `name`, and an `address`; it is born with `active` set to true, marking it currently rentable.

### 3.3. Properties, OTA Platforms, and Collection Agreements

Online travel agencies are modeled as **OTA platforms**, created by a `TaxAdmin` with a `name` and a `registered` flag that defaults to true; only a registered platform may enter collection agreements. Against a platform, an operator (or a `TaxAdmin` on its behalf) proposes an **OTA collection agreement** describing how tax on platform-booked stays is handled. The proposal supplies the `operator_id`, the `platform_id`, a `collection_method`, an `effective_date` marking the inclusive start of coverage, and an optional `end_date` marking an exclusive end; an omitted `end_date` (null) means open-ended coverage. The `collection_method` is either `GROSS` — the platform collects and remits tax on the full room charge, and the operator reports its gross receipts and takes an offsetting OTA credit — or `NET` — the operator simply excludes OTA-collected receipts from its taxable base. A new agreement begins in `PROPOSED`.

Activation is a `TaxAdmin` action moving the agreement from `PROPOSED` to `ACTIVE`, guarded by two checks: the referenced platform's `registered` flag must be true, or the request is rejected with `ERR_PLATFORM_NOT_REGISTERED`; and the agreement's coverage interval, treated as the half-open span from `effective_date` (inclusive) up to `end_date` (exclusive), must not overlap any other already-`ACTIVE` agreement for the same operator-and-platform pair, or it is rejected with `ERR_AGREEMENT_OVERLAP`. An `ACTIVE` agreement can later be moved to `TERMINATED` by a `TaxAdmin`, which is terminal.

### 3.4. Filing a Tax Return: Taxable Base and Tax Computation

An operator's core obligation is the periodic **tax return**. A draft return is created (by a `TaxAdmin` or the operator) with the `operator_id`, a `period_start` and `period_end` bounding the inclusive reporting period, an optional `reporting_method` that defaults to `NET`, and `line_items`: an array of per-property lines, each carrying a `property_id` and that property's `gross_receipts_cents` for the period. On creation the return starts with a filing status of `DRAFT` and a settlement status of `UNPAID`, and the server computes two derived values immediately: `gross_receipts_cents`, the sum of `gross_receipts_cents` across all lines, and the `due_date`, defined as the last day of the month following `period_end` and stamped at UTC midnight of that day (an ISO 8601 timestamp of the form `...T00:00:00.000Z`). A filing is late only when the logical clock is strictly after that instant. The `reporting_method` selects how OTA receipts are treated when the taxable base is derived: under `GROSS` the operator reports the full gross and relies on the OTA credit, while under `NET` receipts collected under an `ACTIVE` OTA agreement are excluded from a line's gross before the taxable amount is derived.

Filing is an operator-only action that advances the return from `DRAFT` to `FILED`. It is guarded by three preconditions. First, the parent operator must be `ACTIVE` or `DELINQUENT` — filing while `PENDING`, `SUSPENDED`, `REVOKED`, or `CLOSED` is rejected with `ERR_OPERATOR_NOT_ACTIVE`. Second, the return's period must not overlap any other non-`SUPERSEDED` return for the same operator, or the filing is rejected with `ERR_PERIOD_OVERLAP`. Third, the receipts must partition cleanly: `gross_receipts_cents` must equal `taxable_receipts_cents` plus `exempt_receipts_cents`. The system maintains this partition by construction — it derives `taxable_receipts_cents` as `gross_receipts_cents` minus `exempt_receipts_cents`, where `exempt_receipts_cents` is the sum of the honored exemption amounts for the return — so the guard's real job is to reject an over-claimed exempt total that would drive the taxable base negative (the honored exemptions exceeding gross receipts), which is rejected with `ERR_RECEIPTS_MISMATCH`.

On a successful filing the server sets `filing_status` to `FILED`, stamps `filed_at` from the logical clock, computes `tax_due_cents`, and posts a `TAX_DUE` ledger entry for that amount (a positive debit), which cascades through the balance and can move the operator to `DELINQUENT`. If the filing happens after the `due_date`, the server additionally computes `penalty_cents` and `interest_cents` for the return and posts `PENALTY` and `INTEREST` ledger entries (both positive debits); those two fields are zero until the return is actually late. The return also exposes `total_due_cents`, the sum of `tax_due_cents`, `penalty_cents`, and `interest_cents`, and `amount_paid_cents`, the total of cleared remittances applied to it (Section 3.6).

**Tax computation.** The tax is computed per line and only then summed, which pins the rounding order. First derive the fractional rate as `tax_rate_bps` divided by 10,000. Then, for each line: determine the line's honored exempt amount and subtract it from the line's `gross_receipts_cents` to get the line's taxable receipts; multiply that taxable amount by the rate; and round that line's tax to whole cents, round-half-up. Because an exemption claim carries no `property_id`, the return's total honored exempt amount is not attributed per property; instead it is allocated across the lines in their listed order — each line absorbs exempt receipts up to its own `gross_receipts_cents`, with any unabsorbed remainder carrying to the next line — so the allocation order (and thus the per-line rounding) follows the line ordering. The return's `tax_due_cents` is the sum of these per-line rounded taxes — each line is rounded first, and the rounded values are added, never the reverse. Which exemptions count as "honored" depends on the variant in play. For an operator's own self-reported return, filed or amended, the honored set is every exemption claim on the return that is `CLAIMED` or `VERIFIED` (that is, not `REJECTED`); this is the STANDARD variant, and it includes claimed-but-not-yet-verified exemptions, producing a lower taxable base and lower tax. The auditor's recomputation (Section 3.8) uses a stricter honored set and is described there.

An operator may amend a `FILED` return, moving it to `AMENDED`, and may amend again from `AMENDED` (the return stays `AMENDED`). An amendment optionally supplies replacement `line_items`. Amendment is blocked when the return is covered by an assessment that has been issued or made final — that is, an `ISSUED` or `FINAL` assessment — in which case it is rejected with `ERR_RETURN_UNDER_ASSESSMENT`. A return is "covered" by such an assessment when the assessment belongs to the same operator and the return's `[period_start, period_end]` overlaps (inclusive/closed-interval) the parent audit's `[period_start, period_end]`. On amendment the server recomputes `tax_due_cents` (STANDARD variant) and posts an `ADJUSTMENT` ledger entry for the delta only, namely the new tax minus the old tax, so the ledger continues to equal the balance. `SUPERSEDED` exists as a terminal, overlap-exempt filing status (a `SUPERSEDED` return is excluded from period-overlap consideration and cannot have its exemptions verified), but no endpoint in this system transitions a return into it: because filing a second return whose period overlaps an existing non-`SUPERSEDED` return is rejected with `ERR_PERIOD_OVERLAP`, there is no replacement-return flow that supersedes a prior return.

### 3.5. Exemption Claims and Verification

Certain receipts are not taxable, and operators declare them as **exemption claims** against a specific return. A claim is created with the `tax_return_id`, an `exemption_type` of `LONG_TERM_30DAY`, `GOVERNMENT`, or `NONPROFIT`, a `guest_ref` identifying the booking, an `amount_cents` of receipts to exempt, and, for long-term stays, a `stay_nights` count of consecutive nights (defaulting to 0 and only meaningful for the `LONG_TERM_30DAY` type). A new claim begins in `CLAIMED`.

A `TaxAdmin` verifies a claim, moving it from `CLAIMED` to `VERIFIED`. Verification requires that the parent return is not `SUPERSEDED`, and, for a `LONG_TERM_30DAY` claim, that `stay_nights` is at least the jurisdiction's `exemption_min_stay_nights`; a long-term claim below that minimum is rejected with `ERR_EXEMPTION_INELIGIBLE`. Verification moves no receipts — a `CLAIMED` or `VERIFIED` exemption is already honored in the operator's STANDARD self-report — so the balance is unaffected.

A `TaxAdmin` may instead reject a claim, moving it from either `CLAIMED` or `VERIFIED` to `REJECTED`, which is terminal. Rejection carries a receipts consequence when the parent return has already been filed: the rejected amount moves out of the exempt bucket and into the taxable bucket, so `taxable_receipts_cents` increases by `amount_cents` and `exempt_receipts_cents` decreases by the same `amount_cents`, leaving `gross_receipts_cents` unchanged (the partition invariant holds). The server then recomputes `tax_due_cents` and posts an `ADJUSTMENT` ledger entry for the resulting tax delta, cascading to the operator's balance. This receipts-movement-and-adjustment applies symmetrically whether the claim was rejected from `CLAIMED` or, as a compensating reversal, from `VERIFIED`.

### 3.6. Remittances, Clearing, and Settlement

Payments against a return are modeled as **remittances**. A remittance is created with the `tax_return_id`, a `remitter` of either `OPERATOR` or `OTA`, an `amount_cents`, and, when the remitter is an OTA, the `ota_agreement_id` under which the platform pays (null when the operator itself pays). A new remittance begins in `RECEIVED`; it has no ledger effect until it clears.

A `TaxAdmin` clears a remittance, moving it from `RECEIVED` to `CLEARED`, under two preconditions. The parent return's filing status must be `FILED` or `AMENDED`, otherwise the clear is rejected with `ERR_INVALID_STATE`. And the payment must not overshoot: `amount_cents` must not exceed the return's remaining balance due, computed as `total_due_cents` minus the already-paid `amount_paid_cents`; an overpayment on the return is rejected with `ERR_REMITTANCE_EXCEEDS_DUE`. When the remitter is an OTA, the referenced OTA agreement must be `ACTIVE` and must cover the return's period, or the clear is rejected with `ERR_OTA_AGREEMENT_INACTIVE`. Coverage is evaluated on the agreement's half-open `[effective_date, end_date)` span containing the return's whole inclusive period: the agreement covers the return when its `effective_date` is at or before the return's `period_start` and its `end_date` is null (open-ended) or strictly after the return's `period_end`. On clearing, the server posts a `REMITTANCE` ledger entry for the negative of the amount (a credit that reduces what the operator owes), which cascades to the balance and can return a `DELINQUENT` operator to `ACTIVE` with the attendant lien release, and it recomputes the return's settlement status.

**Settlement status** — the return's `settlement_status` field — is the return's second, independent axis, driven solely by cleared remittances. Define `amount_paid_cents` as the sum of `amount_cents` over the return's `CLEARED` remittances. If that total is zero or below the return is `UNPAID`; if it is above zero but strictly less than `total_due_cents` the return is `PARTIAL`; and if it reaches or exceeds `total_due_cents` the return is `PAID`. Thus a first clearing that lands strictly between zero and the total due moves `UNPAID` to `PARTIAL`; a later clearing that brings the paid total to at least the total due moves `PARTIAL` to `PAID`; and a single clearing at or above the total due moves `UNPAID` straight to `PAID`. When the last past-due return for an operator reaches `PAID`, the operator may return to `ACTIVE` as part of the same reconciliation.

A cleared remittance can be reversed by a `TaxAdmin`, moving it from `CLEARED` to `REVERSED`, which is terminal. Reversal posts a compensating `REMITTANCE_REVERSAL` ledger entry for the positive amount, restoring the balance so it still equals the ledger sum, and recomputes settlement — which can drop a return from `PAID` back to `PARTIAL` when the reversal pushes the paid total below the total due.

### 3.7. Delinquency, Penalties, Interest, and Liens

When a return is filed late, or an assessment is proposed, the system computes a penalty and interest on the unpaid amount. The base is the return's unpaid tax (or, for an assessment, the deficiency). The number of whole months late is the count of complete 30-day spans between the `due_date` and the logical clock — that is, the elapsed days divided by 30 and taken as a floor — and it is never negative. The penalty rate is a non-linear tiered rate: if the return is not actually late the rate is zero and no penalty applies; otherwise the rate starts at a 10% floor for the first month late and rises by 5 percentage points for each additional month, capped at 25%. Concretely, one month late is 10%, two months is 15%, three months is 20%, and four or more months is held at the 25% cap. The penalty is the base multiplied by this rate, rounded half-up to whole cents. The interest is the base multiplied by the jurisdiction's monthly delinquency rate (`interest_rate_monthly_bps` divided by 10,000) and by the number of months late, again rounded half-up to whole cents. On a late filing these become the return's `penalty_cents` and `interest_cents` and post as `PENALTY` and `INTEREST` ledger entries.

A `Lien` may be recorded against a delinquent operator by a `TaxAdmin`. Recording is guarded first by the optimistic-concurrency check of Section 2.8 on `expected_operator_version`, and then by a threshold: the operator's delinquent balance must strictly exceed the jurisdiction's `lien_threshold_cents`, or the request is rejected with `ERR_BELOW_LIEN_THRESHOLD`. On success the lien snapshots the operator's current `account_balance_cents` into its own `amount_cents`, sets its `status` to `RECORDED`, stamps `recorded_at` from the logical clock, and increments the operator's `version` by exactly one. A lien is released either by an explicit `TaxAdmin` action or automatically by the system when the operator's balance returns to zero or below (Section 2.7); release moves the lien from `RECORDED` to `RELEASED` and freezes `recorded_at`.

### 3.8. Audits, Assessments, and Four-Eyes Issuance

An `Auditor` opens an **audit** on an operator for a coverage window, supplying the `operator_id`, a `period_start`, and a `period_end`; the audit begins in `OPENED` with a `classification` of `NONE`. The auditor begins fieldwork, moving the audit from `OPENED` to `FIELDWORK`. From fieldwork the auditor proposes an **assessment**, which advances the audit to `PROPOSED` and creates the assessment in `PROPOSED`. Proposing requires that at least one `FILED` or `AMENDED` return falls within the audit period, otherwise it is rejected with `ERR_NO_RETURNS_IN_PERIOD`. The set of **audited returns** — used both for this check and for the figures below — is every `FILED` or `AMENDED` return of the audited operator whose `[period_start, period_end]` overlaps (inclusive/closed-interval) the audit's `[period_start, period_end]`. The proposal supplies the auditor-determined `audited_taxable_cents` and a `classification` of `NEGLIGENCE` or `FRAUD`, which is written onto the audit and drives the penalty variant below. The resulting assessment records its parent audit through its `audit_id`.

On proposal the server computes the assessment's figures. The `assessed_tax_cents` is derived directly from the auditor-supplied `audited_taxable_cents` — a single taxable-base figure the auditor determines under the AUDIT variant, in which only `VERIFIED` exemptions are honored (claimed-but-unverified exemptions are excluded), which raises the taxable base and the tax relative to the operator's self-report and is what drives a deficiency. The system computes `assessed_tax_cents` as `audited_taxable_cents` multiplied by the jurisdiction's `tax_rate_bps` divided by 10,000, rounded half-up to whole cents in a single rounding step — it does not re-derive per-return line items or re-round per line. The `self_reported_tax_cents` is the sum of the self-reported `tax_due_cents` across the audited returns (the STANDARD figures), recorded for variance. The `deficiency_cents` is the assessed tax minus the self-reported tax, floored at zero. The assessment's `penalty_cents` is a deficiency penalty whose rate depends on the audit's `classification`: a `NEGLIGENCE` classification applies a flat 10% of the deficiency (not time-tiered), while a `FRAUD` classification applies a flat 25% of the deficiency; each is rounded half-up to whole cents. The assessment's `interest_cents` is interest on the deficiency over the months delinquent, computed the same way as return interest (the base being the deficiency), rounded half-up; the months delinquent are the whole 30-day spans from the **earliest** `due_date` among the audited returns to the logical clock (floored at zero). The `total_assessed_cents` is the sum of `deficiency_cents`, `penalty_cents`, and `interest_cents`.

After a proposal, the auditor may record the taxpayer's response, moving the audit from `PROPOSED` to `RESPONSE` and optionally attaching a `note`. From `RESPONSE` the auditor may reopen fieldwork, returning the audit to `FIELDWORK` for another proposal round; this is the cyclic negotiation path, and it abandons the still-`PROPOSED` assessment by driving it to `ABATED` (a terminal state with no ledger impact, because that assessment was never issued). Alternatively, from `FIELDWORK` the auditor may close the audit with no change, moving it to `CLOSED_NO_CHANGE` with no ledger effect. Reopening requires the current assessment to still be `PROPOSED`.

Issuance is where the **four-eyes** control applies: an assessment is issued by a `TaxAdmin`, never by the auditor who proposed it — issuance is reserved to a `TaxAdmin` acting as a distinct role from the proposing `Auditor`. Issuance is permitted only while the assessment is `PROPOSED` and its parent audit is in `PROPOSED` or `RESPONSE`; otherwise it is rejected with `ERR_INVALID_STATE`. On issuance both the audit and the assessment move to `ISSUED`, and the server posts an `ASSESSMENT` ledger entry for the positive `total_assessed_cents`, which cascades to the operator's balance, can move the operator to `DELINQUENT`, and thereby makes it eligible for a lien.

### 3.9. Appeals, Assessment Resolution, and Refunds

An operator may appeal an issued assessment. Submitting an **appeal** moves the assessment from `ISSUED` to `APPEALED` and creates the appeal in `SUBMITTED`, referencing the assessment through its `assessment_id` and carrying the taxpayer's `grounds`; appeal submission is permitted only while the assessment is `ISSUED`, else `ERR_INVALID_STATE`. A `TaxAdmin` begins review, moving the appeal from `SUBMITTED` to `UNDER_REVIEW`, and may request more information, moving it to `INFO_REQUESTED`. The operator provides the requested information, moving the appeal back to `UNDER_REVIEW` and incrementing its `round_count` by one — this is the cyclic negotiation loop, and `round_count` records how many information cycles have completed.

From `UNDER_REVIEW` a `TaxAdmin` decides the appeal, moving it to `DECIDED` and recording a `decision` of `UPHELD`, `REDUCED`, or `ABATED`. Deciding requires the parent assessment to be `APPEALED`, else `ERR_INVALID_STATE`; and when the decision is `REDUCED`, a `reduced_total_cents` must be provided and must be strictly less than the assessment's `total_assessed_cents`, or the request is rejected with `ERR_INVALID_REQUEST`. The decision then cascades to the assessment. An `UPHELD` decision drives the assessment to `FINAL` — the assessment stands and the ledger is unchanged. An `ABATED` decision drives the assessment to `ABATED` and posts an `ABATEMENT` ledger entry for the negative of `total_assessed_cents`, reversing the original assessment debit and conserving the ledger. A `REDUCED` decision drives the assessment to `FINAL` at the reduced figure and posts an `ADJUSTMENT` ledger entry for the negative of the difference between `total_assessed_cents` and `reduced_total_cents`, crediting back only the reduced portion.

Independently of appeals, an issued or final assessment moves to `SETTLED` — a terminal state — when the operator's `account_balance_cents` returns to zero or below, reflecting that the assessed amount has been paid off.

**Refunds.** An operator (or a `TaxAdmin`) requests a **refund claim** when it holds an overpayment credit, supplying the `operator_id`, a `reason` of `OVERPAYMENT` or `AUDIT_ADJUSTMENT`, the `principal_cents` of overpayment requested, an `overpayment_date` recording when the overpayment was made, and, for a return-level overpayment, an optional `tax_return_id` (null for an account-level claim). The claim begins in `REQUESTED`. A `TaxAdmin` approves it, moving it to `APPROVED`, but only when the operator actually holds a credit at least as large as the principal — that is, the principal must not exceed the magnitude of the operator's negative (credit) balance; a principal larger than the held overpayment credit is rejected with `ERR_REFUND_EXCEEDS_OVERPAYMENT`. On approval the server computes the interest and total.

Refund interest accrues over whole months from an anchor date to the clock at approval, where whole months are the elapsed days divided by 30 taken as a floor. The interest is `principal_cents` multiplied by the jurisdiction's monthly refund rate (`refund_interest_monthly_bps` divided by 10,000) and by that month count, rounded half-up to whole cents, and `total_refund_cents` is `principal_cents` plus that `interest_cents`. The anchor depends on the reason: for a statutory `OVERPAYMENT` the anchor is the earlier `overpayment_date`, yielding more months and more interest; for an `AUDIT_ADJUSTMENT` overpayment arising from an abated or reduced assessment the anchor is the claim's own `created_at`, which is later and yields fewer months and less interest. A `TaxAdmin` may instead deny a claim, moving it from `REQUESTED` to `DENIED`, a terminal state with no ledger effect. An approved claim is paid by a `TaxAdmin`, moving it to `PAID`; payment posts a `REFUND` ledger entry for the positive `total_refund_cents`, which pays down the operator's negative credit balance toward zero.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including state transitions, return `200 OK`. All list and get operations return `200 OK`. Every `GET` endpoint is authorized for `TaxAdmin`, `Operator`, and `Auditor`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/jurisdictions` | Create a jurisdiction | TaxAdmin |
| GET | `/jurisdictions/{jurisdictionId}` | Get a jurisdiction | TaxAdmin, Operator, Auditor |
| POST | `/operators` | Register an operator (PENDING) | TaxAdmin |
| GET | `/operators` | List/filter operators | TaxAdmin, Operator, Auditor |
| GET | `/operators/{operatorId}` | Get an operator | TaxAdmin, Operator, Auditor |
| POST | `/operators/{operatorId}/activate` | Issue certificate, activate | TaxAdmin |
| POST | `/operators/{operatorId}/suspend` | Suspend operator | TaxAdmin |
| POST | `/operators/{operatorId}/reinstate` | Reinstate suspended operator | TaxAdmin |
| POST | `/operators/{operatorId}/revoke` | Revoke certificate | TaxAdmin |
| POST | `/operators/{operatorId}/close` | Close operator account | TaxAdmin |
| POST | `/operators/{operatorId}/liens` | Record a tax lien (OCC on operator version) | TaxAdmin |
| GET | `/operators/{id}/liens` | List liens for an operator | TaxAdmin, Operator, Auditor |
| GET | `/operators/{id}/properties` | List properties for an operator | TaxAdmin, Operator, Auditor |
| GET | `/operators/{id}/ota-agreements` | List OTA agreements for an operator | TaxAdmin, Operator, Auditor |
| GET | `/operators/{id}/returns` | List returns for an operator | TaxAdmin, Operator, Auditor |
| GET | `/operators/{id}/audits` | List audits for an operator | TaxAdmin, Operator, Auditor |
| GET | `/operators/{id}/refund-claims` | List refund claims for an operator | TaxAdmin, Operator, Auditor |
| GET | `/operators/{id}/ledger-entries` | List ledger entries for an operator | TaxAdmin, Operator, Auditor |
| POST | `/properties` | Create a property under an operator | TaxAdmin, Operator |
| GET | `/properties/{propertyId}` | Get a property | TaxAdmin, Operator, Auditor |
| POST | `/ota-platforms` | Create an OTA platform | TaxAdmin |
| GET | `/ota-platforms/{platformId}` | Get an OTA platform | TaxAdmin, Operator, Auditor |
| POST | `/ota-agreements` | Propose an OTA collection agreement | TaxAdmin, Operator |
| GET | `/ota-agreements` | List/filter OTA agreements | TaxAdmin, Operator, Auditor |
| GET | `/ota-agreements/{agreementId}` | Get an OTA agreement | TaxAdmin, Operator, Auditor |
| POST | `/ota-agreements/{agreementId}/activate` | Activate an OTA agreement | TaxAdmin |
| POST | `/ota-agreements/{agreementId}/terminate` | Terminate an OTA agreement | TaxAdmin |
| POST | `/returns` | Create a draft return | TaxAdmin, Operator |
| GET | `/returns/{returnId}` | Get a return | TaxAdmin, Operator, Auditor |
| POST | `/returns/{returnId}/file` | File a return | Operator |
| POST | `/returns/{returnId}/amend` | Amend a filed return | Operator |
| GET | `/returns/{id}/exemptions` | List exemption claims for a return | TaxAdmin, Operator, Auditor |
| GET | `/returns/{id}/remittances` | List remittances for a return | TaxAdmin, Operator, Auditor |
| POST | `/exemptions` | Claim an exemption on a return | TaxAdmin, Operator |
| GET | `/exemptions/{exemptionId}` | Get an exemption claim | TaxAdmin, Operator, Auditor |
| POST | `/exemptions/{exemptionId}/verify` | Verify an exemption | TaxAdmin |
| POST | `/exemptions/{exemptionId}/reject` | Reject an exemption | TaxAdmin |
| POST | `/remittances` | Record a remittance against a return | TaxAdmin, Operator |
| GET | `/remittances` | List/filter remittances | TaxAdmin, Operator, Auditor |
| GET | `/remittances/{remittanceId}` | Get a remittance | TaxAdmin, Operator, Auditor |
| POST | `/remittances/{remittanceId}/clear` | Clear a remittance | TaxAdmin |
| POST | `/remittances/{remittanceId}/reverse` | Reverse a cleared remittance | TaxAdmin |
| POST | `/audits` | Open an audit on an operator | Auditor |
| GET | `/audits/{auditId}` | Get an audit | TaxAdmin, Operator, Auditor |
| POST | `/audits/{auditId}/begin-fieldwork` | Begin fieldwork | Auditor |
| POST | `/audits/{auditId}/assessments` | Propose an assessment | Auditor |
| GET | `/audits/{id}/assessments` | List assessments for an audit | TaxAdmin, Operator, Auditor |
| POST | `/audits/{auditId}/record-response` | Record taxpayer response | Auditor |
| POST | `/audits/{auditId}/reopen-fieldwork` | Return to fieldwork (cyclic) | Auditor |
| POST | `/audits/{auditId}/close-no-change` | Close audit with no change | Auditor |
| GET | `/assessments/{assessmentId}` | Get an assessment | TaxAdmin, Operator, Auditor |
| POST | `/assessments/{assessmentId}/issue` | Issue an assessment (four-eyes) | TaxAdmin |
| POST | `/assessments/{assessmentId}/appeals` | Submit an appeal | Operator |
| GET | `/assessments/{id}/appeals` | List appeals for an assessment | TaxAdmin, Operator, Auditor |
| GET | `/appeals/{appealId}` | Get an appeal | TaxAdmin, Operator, Auditor |
| POST | `/appeals/{appealId}/begin-review` | Begin appeal review | TaxAdmin |
| POST | `/appeals/{appealId}/request-info` | Request more info (cyclic) | TaxAdmin |
| POST | `/appeals/{appealId}/provide-info` | Provide requested info (cyclic) | Operator |
| POST | `/appeals/{appealId}/decide` | Decide an appeal | TaxAdmin |
| POST | `/refund-claims` | Request a refund | TaxAdmin, Operator |
| GET | `/refund-claims` | List/filter refund claims | TaxAdmin, Operator, Auditor |
| GET | `/refund-claims/{refundId}` | Get a refund claim | TaxAdmin, Operator, Auditor |
| POST | `/refund-claims/{refundId}/approve` | Approve a refund (compute interest) | TaxAdmin |
| POST | `/refund-claims/{refundId}/deny` | Deny a refund | TaxAdmin |
| POST | `/refund-claims/{refundId}/pay` | Pay an approved refund | TaxAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | TaxAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_OPERATOR_VERSION` | 412 |
| `ERR_OPERATOR_NOT_ACTIVE` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_AGREEMENT_OVERLAP` | 409 |
| `ERR_PLATFORM_NOT_REGISTERED` | 409 |
| `ERR_OTA_AGREEMENT_INACTIVE` | 409 |
| `ERR_EXEMPTION_INELIGIBLE` | 422 |
| `ERR_RECEIPTS_MISMATCH` | 422 |
| `ERR_REMITTANCE_EXCEEDS_DUE` | 422 |
| `ERR_REFUND_EXCEEDS_OVERPAYMENT` | 422 |
| `ERR_BELOW_LIEN_THRESHOLD` | 422 |
| `ERR_RETURN_UNDER_ASSESSMENT` | 409 |
| `ERR_NO_RETURNS_IN_PERIOD` | 409 |
| `ERR_OPERATOR_NOT_SETTLED` | 409 |
| `ERR_AUDIT_IN_PROGRESS` | 409 |
