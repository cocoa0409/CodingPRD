# Credit Counseling DMP API — Product Requirements Document

## 1. Introduction

Households entering credit counseling rarely arrive with a clean picture of what they owe or what they can afford. The Credit Counseling & Debt Management Plan (DMP) API exists to give a counseling agency a single operational backbone for the entire journey: verifying a household's budget and debt-to-income posture, negotiating concessions with each lender, consolidating everything into one monthly deposit, and then fanning that deposit back out across creditors month after month until the household graduates debt-free.

The platform models the real tension of the business. On one side sits a multi-party negotiation: the agency proposes rate and fee concessions on behalf of the client, and each creditor independently accepts, counters, or rejects across as many rounds as it takes. On the other side sits a ledger-reconciliation engine: once a plan is active, a single consolidated deposit is prorated across enrolled accounts, principal is drawn down cycle by cycle, and provisional balances settle into final ones. Layered on top are the regulated counseling artifacts — budget intake, bankruptcy pre-filing and pre-discharge certificates, and HUD housing counseling — each with its own completion and certification discipline.

This document specifies the API contract end to end. It defines the global conventions every endpoint shares, the cross-cutting fiscal and concurrency principles that protect the ledger, and the detailed business workflows that move a client from intake through activation, disbursement, default and re-age, and ultimately graduation or withdrawal.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `AgencyAdmin`, `Counselor`, and `CreditorRep`. When either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation per the role matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The three roles own different surfaces of the system. The `AgencyAdmin` is an agency operator who provisions agencies, counselors, and the creditor catalog, and who runs the consolidated disbursement cycles. A `Counselor` conducts intake and counseling, manages clients, debt accounts, and the agency side of proposal negotiation, and drives client activation, account drops, re-age, and withdrawal. A `CreditorRep` acts on behalf of a lender, countering, accepting, or rejecting the agency's proposals.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `AgencyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting `Counselor`; ownership checks on any resource that references a `Counselor` compare the resource's counselor foreign key to `X-User-ID`. When `X-User-Role` is `CreditorRep`, `X-User-ID` is the `id` of the acting `Creditor`; ownership checks on any resource that references a `Creditor` compare the resource's creditor foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` is an integer that begins at its initial value and increments by one with every mutation; it underpins the optimistic concurrency control described below.

Two entities are deliberately append-only event records and carry only `id` and `created_at` — they have neither `updated_at` nor `version`. A `DepositRecord` captures a single received deposit and is never modified after creation. A `DisbursementLine` records one prorated principal application and is likewise immutable. Every other entity — `Agency`, `Counselor`, `Creditor`, `Client`, `CounselingSession`, `DebtAccount`, `CreditorProposal`, and `DisbursementRun` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

When the server adjusts a derived or system field on a resource — for example recomputing a client's deposit, drawing down a debt account balance, or advancing a negotiation round — that adjustment is a mutation: it refreshes `updated_at` and increments `version` on the mutated resource. This holds even when the change is triggered indirectly by an operation on a different resource.

### 2.5. Nested and Path-Referenced Resource Resolution

The API uses a flat addressing scheme: every entity is a collection under the `/agencies` prefix, addressed by its own identifier. When a request path carries a resource identifier — such as `agencyId`, `clientId`, `counselorId`, `creditorId`, `debtAccountId`, `proposalId`, `sessionId`, `runId`, `lineId`, or `depositId` — the system validates those identifiers left to right and rejects the first one that does not resolve to an existing resource within the agency with `ERR_NOT_FOUND`. This existence check on path-referenced resources runs before any body-level or business validation.

Foreign-key references supplied in a request body — `counselor_id`, `creditor_id`, `debt_account_id`, and the like — are a separate concern. When a body reference does not resolve to a resource within the acting agency, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This applies when creating a `Client`, creating a `DebtAccount`, creating a `CounselingSession`, and creating a `CreditorProposal`.

### 2.6. Validation Ordering

When several checks apply to a single request, they are evaluated in a fixed priority order so that the most fundamental failure always surfaces first. Header presence and validity is checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Role authorization is checked next (`ERR_FORBIDDEN_FOR_ROLE`). Existence of path-referenced resources is checked third (`ERR_NOT_FOUND`). Resolution of body foreign-key references comes fourth (`ERR_REFERENCE_NOT_FOUND`). State eligibility for the requested transition or operation comes fifth — and for recording a deposit and for dropping an account, the requirement that the owning client is `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`) is part of this state tier and is evaluated before any fiscal or amount validation. After state come the business constraints and fiscal rules in the order presented through the rest of this document: account-reference uniqueness, HUD certification authority, concession validity, accepted-account and intake prerequisites, fee caps, the DTI floor, deposit-amount match, cycle-slot occupation, session-type window occupation, and finally the version check on activation. Wherever two rules could both fire, the earlier one in this ordering wins.

### 2.7. The Consolidated Deposit Ledger and Monetary Precision

The financial heart of the system is the consolidated single-payment model. While a plan is active, the client makes exactly one monthly deposit, and the agency draws its fees and then distributes the remainder across enrolled creditor accounts. All monetary fields are stored and exchanged as integer cents; the field names carry a `_cents` suffix to make this explicit. Aggregations that produce cents — a client's required deposit, a creditor account's balance draw-down — yield integer cents with no rounding ambiguity.

Two derived quantities are percentages rather than cents, and these are computed to two decimal places using the round-half-up method: a client's `front_end_dti` and `back_end_dti`. Wherever a monthly interest figure is derived from a balance and an APR, the result is taken as the floor (the largest integer not exceeding the exact value) of the computed cents, never rounded up. Within the disbursement proration, rounding appears only when ordering fractional remainders during apportionment; the cent amounts that land on each account are never themselves rounded — they are exact integers produced by the apportionment and balance-cap logic described in Section 3.

### 2.8. Hierarchical Consistency and Cascades

A single operation in this system frequently mutates more than one entity, and every such cascade is part of the contract. Activating a client flips its accepted accounts to enrolled and recomputes the client's deposit. Dropping an account recomputes the client's deposit and reshapes the next disbursement. A disbursement run draws down account balances, can settle accounts, can graduate clients, and can default clients — all in one operation. Withdrawing a client cascades drops down to its accounts. When the server propagates such a change to a parent or child, it independently mutates each affected resource, refreshing `updated_at` and bumping `version` as described in Section 2.4. The specific cascades and the states they touch are detailed in Section 3.

### 2.9. Optimistic Concurrency on Client Activation

Client activation is the one operation guarded by optimistic concurrency control, because activation locks in the exact enrollment set and deposit that the caller believes they are committing. The request to activate a DMP must carry `expected_client_version`, the `version` of the target `Client` the caller last observed. A new debt-account enrollment or a freshly accepted proposal recorded after the caller read the client legitimately advances the client's `version` and changes the enrollment set that activation would lock. If `expected_client_version` does not match the client's current `version` at the time of the request, the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from activating a plan whose composition it has not actually observed. Activation is the only endpoint that accepts a version field; no other operation takes one.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Agency, Its Counselors, and the Creditor Catalog

Everything begins with an `AgencyAdmin` standing up an agency by supplying its `name`. Two fee parameters may be supplied at creation and otherwise take their defaults: the one-time `setup_fee_cents`, charged once against a client's deposit at activation, defaults to 5000 and may not exceed a regulatory cap of 5000 cents; and the recurring `monthly_fee_cents`, deducted from each deposit before proration, defaults to 3500 and may not exceed a regulatory cap of 7500 cents. If either fee exceeds its cap at agency creation, the request is rejected with `ERR_FEE_CAP_EXCEEDED`. A newly created agency starts its disbursement cycle counter, `current_cycle_index`, at 0; this counter advances by one each time a disbursement cycle is run.

Within an agency, an `AgencyAdmin` registers counselors and a catalog of creditors. A counselor is created with a `full_name` and an optional `hud_certified` flag (defaulting to false) that governs whether they may issue HUD housing certificates; its `agency_id` is recorded by the system. A counselor's `status` is always `ACTIVE` on creation and has no further lifecycle. Each creditor in the catalog records its `agency_id` and is created with a `name`, a `default_concession_apr` it standardly grants on enrollment (a fraction between 0.0 and 1.0, such as 0.0699), a `waives_late_fees` flag indicating whether it waives accrued late fees when it accepts a proposal (defaulting to true), and a `min_proposed_payment_pct` — the minimum monthly payment, as a fraction of enrolled balance, that the creditor will accept (defaulting to 0.02, between 0.0 and 1.0). The creditor catalog is cross-cutting: debt accounts reference it by id rather than nesting under it.

### 3.2. Client Intake, Budget, and Debt-to-Income

A `Counselor` opens a client file by creating a `Client` with `agency_id`, the assigned `counselor_id`, the client's `full_name`, the verified `gross_monthly_income_cents` (which must be greater than zero), and an optional `housing_payment_cents` for monthly rent or mortgage (defaulting to 0, and excluded from DMP proration). The system records the client's `agency_id` and sets its `status` to `INTAKE`.

Two debt-to-income percentages anchor the intake decision and are recomputed whenever the client or its debts change. The `front_end_dti` is the housing payment divided by gross monthly income, multiplied by 100, taken to two decimal places by round-half-up. The `back_end_dti` is the sum of the housing payment plus the total of the pre-DMP minimum payments across the client's debt accounts that are still in play — those whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED`, or `ENROLLED` — divided by gross monthly income, multiplied by 100, taken to two decimal places by round-half-up. Accounts in `DROPPED` or `SETTLED` status are excluded from this minimum-payment sum. At intake, before any debts exist, back-end DTI reflects only the housing component.

The client also surfaces several other computed quantities once debts are present: `total_enrolled_balance_cents`, the sum of `current_balance_cents` over the client's debt accounts that are enrolled or pending settlement; `projected_payoff_months`, described in Section 3.7; and `monthly_deposit_cents`, the required single consolidated deposit, described in Section 3.5. A system-managed `missed_deposit_streak` counter, described in Section 3.6, starts at 0.

### 3.3. Counseling Sessions and Certificates

A client's counseling work is captured in `CounselingSession` records, each opened by a `Counselor` against a client. Opening a session supplies the conducting `counselor_id` and a `session_type`, one of `BUDGET_INTAKE`, `BANKRUPTCY_PREFILING`, `BANKRUPTCY_PREDISCHARGE`, or `HUD_HOUSING`; the system records the `client_id` and sets `status` to `OPEN`. A client may not open a second session of the same `session_type` while an existing session of that type still occupies its in-flight window — that is, while one is `OPEN` or `NEEDS_REVISION`. The window is half-open and is freed only when the prior session reaches `COMPLETED` or `CERTIFIED`; opening a same-type session while the window is occupied is rejected with `ERR_SESSION_TYPE_IN_FLIGHT`.

A session moves through a revision-capable lifecycle, all transitions driven by a `Counselor`. From `OPEN`, the counselor may send the session back for revision, moving it to `NEEDS_REVISION`; this is allowed only from `OPEN`, otherwise `ERR_INVALID_STATE`. From `NEEDS_REVISION`, resuming returns it to `OPEN`, allowed only from `NEEDS_REVISION`, otherwise `ERR_INVALID_STATE`. This `OPEN` ↔ `NEEDS_REVISION` loop may cycle any number of rounds. Completing a session advances it from `OPEN` to `COMPLETED`, allowed only from `OPEN` (otherwise `ERR_INVALID_STATE`); for a `BUDGET_INTAKE` session specifically, completion additionally requires that the client's `back_end_dti` is at least the minimum enrollment threshold of 15.0 percent, and falling short is rejected with `ERR_DTI_BELOW_THRESHOLD`. A completed `BUDGET_INTAKE` session mints no certificate.

Certification advances a session from `COMPLETED` to `CERTIFIED`, the terminal state, and is performed by a `Counselor`. It is allowed only from `COMPLETED` (otherwise `ERR_INVALID_STATE`) and only for the certifiable session types — `BANKRUPTCY_PREFILING`, `BANKRUPTCY_PREDISCHARGE`, and `HUD_HOUSING`; attempting to certify a `BUDGET_INTAKE` session is rejected with `ERR_SESSION_NOT_CERTIFIABLE`. For a `HUD_HOUSING` session, the conducting counselor's `hud_certified` flag must be true, otherwise the attempt is rejected with `ERR_COUNSELOR_NOT_HUD_CERTIFIED`. On certification, the system mints the session's `certificate_number`; for all other states and for budget-intake sessions this field remains null.

### 3.4. Building the Debt Portfolio and Negotiating Concessions

A `Counselor` adds a debt account to a client by supplying the `creditor_id` from the catalog, a masked `account_ref`, the `original_balance_cents` (greater than zero), the pre-DMP `original_apr` (a fraction between 0.0 and 1.0), the pre-DMP `min_payment_cents` (greater than zero, used in back-end DTI), the `proposed_monthly_payment_cents` toward this account under the single plan (greater than zero, and the account's weight in proration), and an optional `requested_concession_apr`. The account's `account_ref` must be unique among the client's accounts that are not `DROPPED`; a collision is rejected with `ERR_DUPLICATE_ACCOUNT_REF`. The proposed monthly payment must be at least the creditor's `min_proposed_payment_pct` multiplied by the original balance; falling below that floor is rejected with `ERR_INVALID_CONCESSION`. A new account is created in status `PROPOSED`, the system records its `client_id`, and the client's `back_end_dti` and `monthly_deposit_cents` are recomputed to reflect the addition.

Creating an account automatically opens the first round of negotiation: a `CreditorProposal` is created in status `SUBMITTED` with `round_index` 1, carrying the account's `requested_concession_apr` (defaulting to the creditor's `default_concession_apr` when not supplied) and a `requested_waive_late_fees` flag (defaulting to true). The system records the proposal's `debt_account_id` and `creditor_id`. The account exposes a convenience `proposal_id` back-reference to its latest proposal — the one with the highest `round_index` — though the full proposal history is discoverable through the account's proposal listing. A `concession_apr` on the account stays null until a proposal is accepted.

The proposal then enters a negotiation cycle owned jointly by the creditor and the agency. A `CreditorRep` may counter a `SUBMITTED` proposal: this requires a `countered_concession_apr` that is strictly below the account's `original_apr` (a non-strict or missing value is rejected with `ERR_INVALID_CONCESSION`), records that countered APR, advances the proposal from `SUBMITTED` to `COUNTERED`, and as a side effect moves the underlying account from `PROPOSED` to `COUNTERED`. Countering is allowed only from `SUBMITTED`, otherwise `ERR_INVALID_STATE`. In response, a `Counselor` may resubmit a `COUNTERED` proposal with a new `requested_concession_apr` (required, otherwise `ERR_INVALID_CONCESSION`); resubmission increments `round_index` by one, returns the proposal from `COUNTERED` to `SUBMITTED`, and moves the account from `COUNTERED` back to `PROPOSED`. Resubmission is allowed only from `COUNTERED`, otherwise `ERR_INVALID_STATE`. This `SUBMITTED` ↔ `COUNTERED` loop may run across as many rounds as the parties need.

Acceptance ends negotiation favorably and exists in two symmetric forms. A `CreditorRep` may accept a `SUBMITTED` proposal directly: the proposal advances `SUBMITTED` → `ACCEPTED`, the account's `concession_apr` is set to the proposal's `requested_concession_apr`, and the account advances `PROPOSED` → `ACCEPTED`; allowed only from `SUBMITTED`, otherwise `ERR_INVALID_STATE`. Alternatively, a `Counselor` may accept the creditor's counter on a `COUNTERED` proposal: the proposal advances `COUNTERED` → `ACCEPTED`, the account's `concession_apr` is set to the proposal's `countered_concession_apr`, and the account advances `COUNTERED` → `ACCEPTED`; allowed only from `COUNTERED`, otherwise `ERR_INVALID_STATE`. In both forms, when the creditor's `waives_late_fees` flag is true, accrued late fees are treated as waived at this point (a no-op against the balance in this model). `ACCEPTED` and `REJECTED` are the terminal proposal states.

Rejection ends negotiation unfavorably and may be issued by a `CreditorRep` from either `SUBMITTED` or `COUNTERED`; in both cases the proposal moves to `REJECTED` and, as a cascade, the underlying account moves to `DROPPED` (from `PROPOSED` when the proposal was `SUBMITTED`, from `COUNTERED` when it was `COUNTERED`). Rejection from any other proposal state is rejected with `ERR_INVALID_STATE`.

### 3.5. Activating the Plan and Locking the Monthly Deposit

Once a household has at least one accepted account and a completed budget intake, a `Counselor` activates the DMP. Activation is the system's most heavily guarded operation, and its preconditions are evaluated in order. First, the supplied `expected_client_version` must match the client's current `version`, or the request is rejected with `ERR_STALE_VERSION` as described in Section 2.9. There must exist a `BUDGET_INTAKE` session for the client that has reached `COMPLETED` or `CERTIFIED`, or the request is rejected with `ERR_INTAKE_NOT_COMPLETE`. At least one of the client's debt accounts must be in `ACCEPTED` status, or the request is rejected with `ERR_NO_ACCEPTED_ACCOUNTS`. The client's `back_end_dti` must be at least the 15.0 percent enrollment floor, or the request is rejected with `ERR_DTI_BELOW_THRESHOLD`. The agency's `setup_fee_cents` and `monthly_fee_cents` must each remain within their regulatory caps of 5000 and 7500 cents respectively, or the request is rejected with `ERR_FEE_CAP_EXCEEDED`.

When activation succeeds, several effects fire together. Every `ACCEPTED` debt account of the client cascades to `ENROLLED`, and each enrolled account's `current_balance_cents` is initialized to its `original_balance_cents`. The client's required `monthly_deposit_cents` is computed as the agency's `monthly_fee_cents` plus the sum of `proposed_monthly_payment_cents` across the now-enrolled accounts. The client advances from `INTAKE` to `ACTIVE`, and the client's `version` is incremented by one. This recomputation of the deposit also occurs whenever the enrolled set changes — notably when an account is later dropped.

A `Counselor` may withdraw a client whose status is `INTAKE` or `ACTIVE`, moving it to the terminal `WITHDRAWN` state; an attempt from any other status is rejected with `ERR_INVALID_STATE`. Withdrawal cascades down: every one of the client's debt accounts that is not already in a terminal state is moved to `DROPPED`.

Dropping a single enrolled account is a narrower operation, performed by a `Counselor`, and is permitted only when the account is `ENROLLED` (otherwise `ERR_INVALID_STATE`) and the owning client is `ACTIVE` (otherwise `ERR_CLIENT_NOT_ACTIVE`, checked as part of the state tier before any fiscal validation). Dropping moves the account from `ENROLLED` to `DROPPED`, recomputes the client's `monthly_deposit_cents` excluding the dropped account, and reshapes the next disbursement so that proration re-spreads across the remaining enrolled accounts.

### 3.6. The Deposit and Disbursement Cycle

A consolidated deposit is recorded against a client by a `Counselor` or an `AgencyAdmin`, who supplies the `amount_cents`. The owning client must be `ACTIVE`, checked first within the state tier and before the amount is examined; a deposit against a non-active client is rejected with `ERR_CLIENT_NOT_ACTIVE`. The deposit creates a `DepositRecord` stamped with the agency's `current_cycle_index` as its `cycle_index` and with `posted` set to true; the `client_id` is recorded by the system. The deposited amount must exactly equal the client's `monthly_deposit_cents`, or the request is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`. At most one deposit may exist per client per cycle: a second deposit at the same `current_cycle_index` for the same client is rejected with `ERR_DUPLICATE_CYCLE_DEPOSIT`. Recording a deposit resets the client's `missed_deposit_streak` to 0.

An `AgencyAdmin` runs a disbursement cycle across the whole agency. This first advances the agency's `current_cycle_index` by one, then processes every `ACTIVE` client, and produces a `DisbursementRun` recording the run's `cycle_index`, the computed `clients_processed` (count of active clients processed), `clients_defaulted` (count pushed to default in this run), and `total_disbursed_cents` (the sum of every line amount produced). The run's `agency_id` is recorded and its `status` is always `COMPLETED`.

For each active client that has a `DepositRecord` at the run's cycle, the agency first sets aside the disbursable principal as the deposit's `amount_cents` minus the agency's `monthly_fee_cents`. The eligible accounts are those that are `ENROLLED` with a `current_balance_cents` greater than zero; each account's `proposed_monthly_payment_cents` is its apportionment weight. The disbursable principal is apportioned across these accounts by the largest-remainder (Hamilton) method: for each eligible account, the exact share is the disbursable principal multiplied by that account's weight divided by the total of all weights, and the account's initial target is the floor of that exact share. The leftover cents — the disbursable principal minus the sum of those floored targets — are distributed one cent at a time to accounts ordered by the descending fractional part of their exact share, breaking ties by ascending account `created_at`. Each account's line is then capped at its remaining `current_balance_cents`; any overflow created by capping re-flows to the still-under-cap eligible accounts in ascending `created_at` order until the overflow is exhausted or all accounts are capped. The cent amounts themselves are never rounded — rounding enters only in ordering the fractional parts.

Each disbursed account's `current_balance_cents` is then reduced by its line amount, and the system writes one `DisbursementLine` per disbursed account recording its `disbursement_run_id`, `client_id`, `debt_account_id`, the `amount_cents` applied, and the resulting `balance_after_cents`. When an account's balance reaches exactly 0, it transitions from `ENROLLED` to `SETTLED`. When every one of a client's enrolled accounts has settled — more precisely, when every debt account of the client is either `SETTLED` or `DROPPED` with at least one `SETTLED` — the client bubbles up from `ACTIVE` to the terminal `GRADUATED` state.

For each active client that has no deposit recorded at the run's cycle, the client's `missed_deposit_streak` is incremented by one. When that streak reaches the missed-deposit limit of 3 consecutive cycles, the client is moved from `ACTIVE` to `DEFAULTED` and is held — no disbursements occur for a client while it is `DEFAULTED`. A client that has recorded a deposit keeps its streak at the 0 the deposit set.

A `DEFAULTED` client is rehabilitated by a `Counselor` through re-age, which returns the client from `DEFAULTED` to `ACTIVE`. Re-age is permitted only when the client is `DEFAULTED` (otherwise `ERR_INVALID_STATE`) and only when a `DepositRecord` exists for the client at the agency's current `current_cycle_index` (otherwise `ERR_NO_CURRENT_DEPOSIT`); on success it resets the client's `missed_deposit_streak` to 0.

### 3.7. Payoff Projection and Concession Savings

Two reporting capabilities let counselors and admins quantify the plan. The forward-looking payoff projection estimates how many months the client needs to clear the plan, assuming the concession APR accrues monthly on each balance and the full proposed monthly payment is applied each cycle. For each enrolled account with a positive balance, the monthly interest is the floor of the account's `current_balance_cents` multiplied by its `concession_apr` divided by 12; the net principal is the account's `proposed_monthly_payment_cents` minus that monthly interest. If that net principal is zero or negative, the account does not amortize and the projection is rejected with `ERR_NON_AMORTIZING_PLAN`. Otherwise the months for that account is the ceiling of its current balance divided by its net principal, and the client's `projected_payoff_months` is the maximum of these per-account month counts across the enrolled accounts. This forward estimate ignores the rounding drift of actual disbursements; the settled-actual counterpart — the count of disbursement cycles a client actually consumed to reach all-settled — is a purely chronological figure with no interest model, realized when graduation occurs.

The concession savings breakdown reports, for a single account that is `ACCEPTED` or `ENROLLED` (and therefore has a non-null `concession_apr`), how much interest the concession saves each month; requesting it for an account without a concession is rejected with `ERR_INVALID_STATE`. The basis is the account's `current_balance_cents` when it is `ENROLLED`, or its `original_balance_cents` when it is merely `ACCEPTED` and not yet enrolled. The `original_monthly_interest_cents` is the floor of that basis multiplied by `original_apr` divided by 12; the `concession_monthly_interest_cents` is the floor of that basis multiplied by `concession_apr` divided by 12 (and stays null until a concession is set); and the `monthly_interest_savings_cents` is the original figure minus the concession figure. A late-fee waiver is reflected only when the creditor's `waives_late_fees` is true and the account is `ACCEPTED` or `ENROLLED`. Accounts whose `original_apr` exceeds the high-interest threshold of 0.10 are flagged as high-interest in this breakdown.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an agency, counselor, creditor, client, session, debt account, deposit, or disbursement run — return `201 Created`. Operations that modify an existing resource, including all state-transition actions, return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies/agencies` | Create a counseling agency | AgencyAdmin |
| GET | `/agencies/agencies/{agencyId}` | Get an agency | AgencyAdmin, Counselor, CreditorRep |
| POST | `/agencies/agencies/{agencyId}/run_disbursement` | Execute one consolidated disbursement cycle across all active clients | AgencyAdmin |
| GET | `/agencies/disbursement-runs/{runId}` | Get a disbursement run | AgencyAdmin, Counselor |
| GET | `/agencies/disbursement-runs` | List disbursement runs | AgencyAdmin, Counselor |
| GET | `/agencies/disbursement-lines/{lineId}` | Get a disbursement line | AgencyAdmin, Counselor |
| GET | `/agencies/disbursement-lines` | List disbursement lines | AgencyAdmin, Counselor |
| POST | `/agencies/counselors` | Create a counselor | AgencyAdmin |
| GET | `/agencies/counselors/{counselorId}` | Get a counselor | AgencyAdmin, Counselor |
| GET | `/agencies/counselors` | List counselors | AgencyAdmin, Counselor |
| POST | `/agencies/creditors` | Create a creditor in the catalog | AgencyAdmin |
| GET | `/agencies/creditors/{creditorId}` | Get a creditor | AgencyAdmin, Counselor, CreditorRep |
| GET | `/agencies/creditors` | List creditors | AgencyAdmin, Counselor, CreditorRep |
| POST | `/agencies/clients` | Create a client (intake) | Counselor |
| GET | `/agencies/clients/{clientId}` | Get a client with computed deposit/DTI/balance | AgencyAdmin, Counselor |
| GET | `/agencies/clients` | List clients | AgencyAdmin, Counselor |
| POST | `/agencies/clients/{clientId}/activate` | Activate the DMP | Counselor |
| POST | `/agencies/clients/{clientId}/re_age` | Re-age a defaulted client back to active | Counselor |
| POST | `/agencies/clients/{clientId}/withdraw` | Withdraw a client; drop non-terminal accounts | Counselor |
| POST | `/agencies/clients/{clientId}/deposits` | Record a consolidated deposit for the current cycle | Counselor, AgencyAdmin |
| POST | `/agencies/clients/{clientId}/sessions` | Open a counseling session | Counselor |
| POST | `/agencies/clients/{clientId}/debt-accounts` | Add a debt account (auto-creates first proposal) | Counselor |
| GET | `/agencies/clients/{clientId}/payoff_projection` | Forward-looking projected payoff months | AgencyAdmin, Counselor |
| GET | `/agencies/deposits/{depositId}` | Get a deposit record | AgencyAdmin, Counselor |
| GET | `/agencies/deposits` | List deposit records | AgencyAdmin, Counselor |
| GET | `/agencies/sessions/{sessionId}` | Get a counseling session | AgencyAdmin, Counselor |
| GET | `/agencies/sessions` | List counseling sessions | AgencyAdmin, Counselor |
| POST | `/agencies/sessions/{sessionId}/request_revision` | Send a session back for revision | Counselor |
| POST | `/agencies/sessions/{sessionId}/resume` | Resume a session under revision | Counselor |
| POST | `/agencies/sessions/{sessionId}/complete` | Complete a session | Counselor |
| POST | `/agencies/sessions/{sessionId}/certify` | Issue a certificate for a bankruptcy/HUD session | Counselor |
| GET | `/agencies/debt-accounts/{debtAccountId}` | Get a debt account | AgencyAdmin, Counselor, CreditorRep |
| GET | `/agencies/debt-accounts` | List debt accounts | AgencyAdmin, Counselor, CreditorRep |
| POST | `/agencies/debt-accounts/{debtAccountId}/drop` | Drop an enrolled debt account | Counselor |
| GET | `/agencies/debt-accounts/{debtAccountId}/savings` | Concession savings breakdown | AgencyAdmin, Counselor |
| GET | `/agencies/proposals/{proposalId}` | Get a creditor proposal | AgencyAdmin, Counselor, CreditorRep |
| GET | `/agencies/proposals` | List creditor proposals | AgencyAdmin, Counselor, CreditorRep |
| POST | `/agencies/proposals/{proposalId}/counter` | Creditor counters with a different concession APR | CreditorRep |
| POST | `/agencies/proposals/{proposalId}/resubmit` | Counselor resubmits a revised concession request | Counselor |
| POST | `/agencies/proposals/{proposalId}/accept` | Creditor accepts the submitted proposal | CreditorRep |
| POST | `/agencies/proposals/{proposalId}/accept_counter` | Counselor accepts the creditor's counter | Counselor |
| POST | `/agencies/proposals/{proposalId}/reject` | Creditor rejects the proposal; account is dropped | CreditorRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_ACCOUNT_REF` | 409 |
| `ERR_INVALID_CONCESSION` | 422 |
| `ERR_SESSION_NOT_CERTIFIABLE` | 409 |
| `ERR_COUNSELOR_NOT_HUD_CERTIFIED` | 409 |
| `ERR_DTI_BELOW_THRESHOLD` | 409 |
| `ERR_NO_ACCEPTED_ACCOUNTS` | 409 |
| `ERR_INTAKE_NOT_COMPLETE` | 409 |
| `ERR_FEE_CAP_EXCEEDED` | 422 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 |
| `ERR_DUPLICATE_CYCLE_DEPOSIT` | 409 |
| `ERR_SESSION_TYPE_IN_FLIGHT` | 409 |
| `ERR_NO_CURRENT_DEPOSIT` | 409 |
| `ERR_NON_AMORTIZING_PLAN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
