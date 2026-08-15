# Deposit Operations & Account Maintenance API — Product Requirements Document

## 1. Introduction

A bank's deposit operations back office owns the slow, heavily regulated half of an account's life: maintaining signature cards and authorized signers, retitling accounts as customers marry, incorporate, or fund trusts, handling death claims and estate disbursement, answering garnishments and levies without surrendering legally exempt funds, tracking dormancy through to escheat, producing or lawfully suppressing statements, converting products and rates, and finally closing accounts while accounting for every last cent. Each of these workflows carries regulatory exposure, and several of them intersect — a death in the family collides with an in-flight retitle, a levy collides with a closure request — so the system behind them must be exact about who may act, in what order checks fire, and how money is conserved through every transition.

This document specifies the Deposit Operations & Account Maintenance API, mounted under `/bank`, for that back office. It defines a segregation-of-duties role model in which the officer who initiates a sensitive workflow can never be the manager who completes it, a two-dimensional account posture that separates the activity lifecycle from legal restrictions, an append-only ledger from which balances and holds are derived, and a logical clock that makes every deadline, dormancy window, and nightly sweep deterministic. All monetary values are integer cents and all interest math follows pinned rounding variants, so that two independent implementations of this document produce identical figures.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, resource conventions, the clock, monetary precision, ledger invariants, account posture, retrieval and validation order, and concurrency control.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or naming a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

Four roles exist. `OpsOfficer` is the deposit operations specialist: opens accounts, posts transactions, maintains signers and document intake, files title changes and deceased reports, registers garnishments, schedules statement cycles and conversions, and initiates estate releases. `OpsManager` is the operations manager: reviews documents, verifies deaths, approves title changes and estate releases, resolves garnishments, and runs the daily sweep — and is bound by segregation-of-duties rules that prevent a manager from approving, resolving, or verifying what the same user initiated. `System` is the automation principal behind the nightly sweep, scheduled conversion execution, system transaction postings, and statement scheduling. `Auditor` is a read-only oversight role limited to retrieval endpoints. An attempt to perform an action outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For all four roles — `OpsOfficer`, `OpsManager`, `System`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow captures an actor (for example `created_by_user_id` on a title change request, `reviewed_by_user_id` on a document, `received_by_user_id` and `resolved_by_user_id` on a garnishment order, `initiated_by_user_id` and `approved_by_user_id` on a deceased case) and compares those recorded identifiers when enforcing segregation of duties, but it never compares `X-User-ID` against any entity's `id`.

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

List endpoints paginate through two query parameters: `limit`, the maximum number of items returned, which defaults to 10 and accepts a minimum of 1 and a maximum of 100; and `offset`, the number of items skipped, which defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource — accounts, signers, documents, title change requests, deceased cases, garnishment orders, statement cycles, and product conversions — carries a standard system-managed set of fields. The `id` is a unique server-generated identifier formatted as a UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is the same format, refreshed upon any change to the resource. The `version` is a system-managed integer that increments by exactly one on every mutation and underpins optimistic concurrency control where that applies.

One deliberate exception exists: the account transaction is an append-only event log whose only state is `POSTED` — initial and terminal at once. A posted transaction carries only `id` and `created_at`; `updated_at` and `version` are absent, because a posted transaction never changes state, has no update endpoint, and cannot be deleted.

### 2.5. The Logical Clock and Calendar Semantics

The server never reads the wall clock. A logical UTC clock governs every date the system stamps or compares: default value dates on transactions, garnishment answer deadlines, the daily sweep date, dormancy inactivity windows, and conversion due dates all read this clock. Before any explicit set, the clock reads exactly 2026-08-01T00:00:00Z. A clock-setting capability available to `OpsManager` and `System` advances the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`.

Calendar dates travel as `YYYY-MM-DD` strings. Two interval conventions recur throughout this document and are always honored exactly: interest accrual windows and statement periods are half-open — inclusive of their start date and exclusive of their end date — while the garnishment lookback window and service window are closed, inclusive of both endpoints.

### 2.6. Money, Interest Rates, and Rounding Discipline

All monetary amounts in this API are integer cents — never fractional, never floating point. Fields such as `balance_cents`, `amount_cents`, and `held_amount_cents` are whole numbers of cents, and every derived monetary figure is likewise an integer number of cents.

Interest rates are expressed as integer basis points in `rate_bps` (and `new_rate_bps` on conversions), bounded inclusively between 0 and 2000; non-interest products carry a rate of 0.

Interest accrual follows one of two pinned rounding variants. The accrual window is always half-open: interest accrues once per calendar day from `accrual_start_date` up to but not including the settlement date. The balance attributed to a day is that day's end-of-day balance — the `balance_after_cents` of the most recent transaction whose `posted_date` falls on or before that day; the balance carries forward across days without postings, and it is zero before the account's first transaction. A day's raw interest is that day's balance multiplied by the `rate_bps` in force, divided by ten thousand, then divided by 365, kept as an exact rational amount with no intermediate rounding. Under the STANDARD variant, which applies to `BASIC_CHECKING`, `PREMIUM_CHECKING`, and `SAVINGS`, each day's raw interest is first rounded half-up to whole cents and the rounded daily amounts are then summed. Under the SIMPLE variant, which applies to `MONEY_MARKET`, the exact raw daily amounts are summed first and a single half-up rounding to whole cents is applied once at the end. The two variants can differ by cents for the same balance series, so the applicable variant is always pinned — by the product in force during the window, or by an explicit rule where this document names one, as with deceased-case snapshots.

The exempt-funds analysis, estate release amounts, and inactivity-fee arithmetic use integer cents throughout with no rounding at any step.

### 2.7. Ledger Integrity: Balances, Holds, and Available Funds

Every deposit account is a ledger. Its `balance_cents` is the signed sum of the amounts of all posted transactions on the account, and each posting records `balance_after_cents`, the balance immediately after that transaction posts. Direction is derived from the transaction type, never from the sign of `amount_cents`, which is always positive: `DEPOSIT`, `FEDERAL_BENEFIT_DEPOSIT`, and `INTEREST_CREDIT` are credits, while `WITHDRAWAL`, `INACTIVITY_FEE`, `LEGAL_REMITTANCE`, `CLOSURE_PAYOUT`, and `ESTATE_RELEASE` are debits. Every child record the API returns also exposes its `account_id`, identifying the account it belongs to.

Legal holds are tracked separately from the ledger balance. An account's `total_held_cents` is the sum of `held_amount_cents` over exactly its garnishment orders in `FUNDS_HELD` status — orders in `REMITTED` or `RELEASED` contribute nothing — and its `available_balance_cents` is `balance_cents` minus `total_held_cents`. Both derived figures are recomputed whenever a garnishment order is registered or resolved and whenever any transaction posts.

The account additionally carries `accrued_interest_cents`, the unsettled interest accrued over the half-open window from `accrual_start_date` up to the settlement date, computed per the accrual rule of §2.6; it starts at zero and is recomputed at settlement events.

### 2.8. Two-Dimensional Account Posture

A deposit account carries two independent status dimensions that gate operations independently. The `lifecycle_status` — `OPEN`, `DORMANT`, `ESCHEAT_PENDING`, or `CLOSED` — governs activity, dormancy, and closure; `CLOSED` is the only terminal state. The `restriction_status` — `NONE`, `LEGAL_HOLD`, or `DECEASED_HOLD` — governs legal posture and blocks operations such as withdrawals, title changes, and closure while anything other than `NONE` is in force.

From these two dimensions the server derives `statement_suppression`, evaluated in strict precedence: `CLOSED` when the lifecycle is `CLOSED`; otherwise `DECEASED` when the restriction is `DECEASED_HOLD`; otherwise `DORMANT` when the lifecycle is `DORMANT` or `ESCHEAT_PENDING`; otherwise `NONE`. The derivation is recomputed on every posture change.

Posture changes are never silent. Every transition that mutates the account increments its `version` by exactly one and refreshes `updated_at`, and cascades into child records — suspending signers, auto-rejecting title requests, cancelling conversions, suppressing statement cycles — ride along inside the same mutation, so a reader of the account always sees a consistent aggregate.

### 2.9. Nested Resource Retrieval

Every child collection hangs directly off an account, and requests that address nested resources validate path identifiers in strict left-to-right order: the account `id` first, then the child identifier. The first identifier that fails to resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any later validation runs — a request against a garnishment collection of a non-existent account reports the missing account, not the missing order. Standalone action paths address their target by a bare identifier — `signerId`, `documentId`, `requestId`, `caseId`, `orderId`, or `conversionId` — and the same existence rule applies to each.

### 2.10. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. The tiers, from first to last:

1. **User context** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the caller's role is permitted on the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Existence** — every path identifier resolves, left to right (`ERR_NOT_FOUND`).
4. **Request shape** — required fields are present, enum members are valid, amounts are positive, `pod_beneficiary_name` is present exactly when the ownership type in play is `POD`, a requested type differs from the current one, and `cycle_start` falls strictly before `cycle_end` (`ERR_INVALID_REQUEST`).
5. **State and version** — the target resource's state permits the transition (`ERR_INVALID_STATE`), and where optimistic concurrency applies the presented `expected_account_version` matches the account's current `version` (`ERR_STALE_VERSION`).
6. **Compliance gates** — restriction posture (`ERR_ACCOUNT_RESTRICTED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), closure blocking (`ERR_CLOSURE_BLOCKED`), and required-document completeness (`ERR_DOCUMENTS_INCOMPLETE`).
7. **Uniqueness and intervals** — one active request per child collection (`ERR_ACTIVE_REQUEST_EXISTS`), document reference uniqueness per account (`ERR_DUPLICATE_REFERENCE`), statement-period overlap (`ERR_STATEMENT_PERIOD_OVERLAP`), and legal-order service-window conflict (`ERR_LEGAL_ORDER_WINDOW_CONFLICT`).
8. **Clock-relative rules** — future-dated service or death dates (`ERR_DATE_RANGE_INVALID`), conversion scheduling and due dates (`ERR_EFFECTIVE_DATE_NOT_FUTURE`, `ERR_CONVERSION_NOT_DUE`), and the garnishment answer period (`ERR_ANSWER_PERIOD_NOT_ELAPSED`).
9. **Funds sufficiency** — withdrawal coverage (`ERR_INSUFFICIENT_AVAILABLE_FUNDS`) and remit-override coverage (`ERR_AMOUNT_EXCEEDS_COLLECTIBLE`).

Ordering decides which error a doubly-invalid request reports. A missing header rejects before any role check runs; a stale account version surfaces as `ERR_STALE_VERSION` even when a compliance gate would also have failed; and a withdrawal that is both restricted and unaffordable reports `ERR_ACCOUNT_RESTRICTED`, not the funds error.

### 2.11. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency against the parent account: filing a title change request against an account, and closing an account. Both require the request body to carry `expected_account_version`, a non-optional field holding the account `version` the client last observed. If the account's current `version` has advanced past the presented value — because a hold was placed, a fee posted, a transaction landed, or any other mutation intervened — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the account and re-issue with the fresh version.

The rationale differs slightly per operation. A title change is registered against the account and itself bumps the account's `version`, so a filer working from a stale account view must re-read before filing. For closure the stakes are monetary: intervening mutations change the residual payout basis, so closure requires the version the officer actually reviewed. No endpoint other than these two takes a version field.

## 3. Business Logic & Workflows

### 3.1. Opening Accounts and Posting Transactions

An `OpsOfficer` or `OpsManager` opens a deposit account by supplying the primary owner's legal name in `primary_owner_name` and tax identifier in `owner_tax_id`, choosing an `ownership_type` of `INDIVIDUAL`, `JOINT`, `POD`, `TRUST`, or `BUSINESS`, and selecting a `product_code` of `BASIC_CHECKING`, `PREMIUM_CHECKING`, `SAVINGS`, or `MONEY_MARKET` together with its `rate_bps`. The rate is bounded inclusively between 0 and 2000 basis points and is 0 for non-interest products. When — and only when — the ownership type is `POD`, the request must also name a `pod_beneficiary_name`; omitting it for a POD account, supplying an unknown enum member, a non-positive amount, or a rate outside the bounds fails shape validation with `ERR_INVALID_REQUEST`. The opening funds arrive as `opening_deposit_cents`.

Creation leaves the account in lifecycle `OPEN` with restriction `NONE`. The server mints a unique ten-digit `account_number`, posts the opening deposit as a customer-initiated `DEPOSIT` transaction, sets `balance_cents` to the opening amount, and anchors interest accrual by stamping `accrual_start_date` with the logical clock date; that same date seeds `last_customer_activity_date`. Derived fields start clean — `total_held_cents` and `accrued_interest_cents` at zero, `available_balance_cents` equal to the balance, `statement_suppression` at `NONE`, `dormant_since_date` null, `fees_assessed_count` at zero, and both `closure_payout_cents` and `closure_payout_destination` null — and the new account's `version` is 1. Accounts can be listed with optional `status` and `ownership_type` filters.

From then on, an `OpsOfficer` (or the `System` principal for automated postings) posts customer-facing transactions of type `DEPOSIT`, `WITHDRAWAL`, or `FEDERAL_BENEFIT_DEPOSIT`; the remaining types — `INACTIVITY_FEE`, `INTEREST_CREDIT`, `LEGAL_REMITTANCE`, `CLOSURE_PAYOUT`, and `ESTATE_RELEASE` — are system-only and are never accepted from clients. Each posting carries a positive `amount_cents`, an optional `customer_initiated` flag that defaults to false, and an optional `posted_date` value date that defaults to the logical clock date; the server records the resulting `balance_after_cents`. Credits post under any restriction posture. A `WITHDRAWAL`, by contrast, is rejected with `ERR_ACCOUNT_RESTRICTED` whenever the account's restriction is anything other than `NONE`, and with `ERR_INSUFFICIENT_AVAILABLE_FUNDS` when its amount exceeds the account's `available_balance_cents` — and when both failures coincide, the restriction gate reports first. An account's transaction ledger can be listed with an optional `txn_type` filter.

Customer-initiated activity is the heartbeat that drives dormancy. When a posting arrives with `customer_initiated` set to true, the account's `last_customer_activity_date` advances to the transaction's `posted_date`. If the account was `DORMANT` or `ESCHEAT_PENDING` and its restriction is `NONE`, the same posting reactivates it to `OPEN`: `dormant_since_date` clears to null, `fees_assessed_count` resets to zero, ending the dormancy episode, and `statement_suppression` is recomputed. A customer-initiated posting against a restricted dormant account is rejected with `ERR_ACCOUNT_RESTRICTED` and does not reactivate. Every posted transaction recomputes the account's derived totals and increments its `version`.

### 3.2. Account Documents and Authorized Signers

Paperwork enters the system as account documents. An `OpsOfficer` submits a document onto an account by declaring its `doc_type` — one of `SIGNATURE_CARD`, `DEATH_CERTIFICATE`, `LETTERS_TESTAMENTARY`, `TRUST_AGREEMENT`, `POD_DESIGNATION`, `BUSINESS_RESOLUTION`, or `COURT_ORDER` — together with a submitter-chosen `reference_number`. The reference is unique per account across all statuses: reusing a reference already on file, even one belonging to a previously rejected document, is rejected with `ERR_DUPLICATE_REFERENCE`. New documents land in `SUBMITTED`.

Review is a manager's act. An `OpsManager` reviews a submitted document with a `decision` of `VERIFIED` or `REJECTED` and may attach a `review_note`. Only a document still in `SUBMITTED` can be reviewed — re-deciding a decided document fails with `ERR_INVALID_STATE` — and both outcomes are terminal. Either way the review records the deciding manager in `reviewed_by_user_id`, which stays null until that moment, and stores the note. An account's documents can be listed filtered by `doc_type` or `status`.

Signers sit on top of verified paperwork. Adding an authorized signer — an officer-only action supplying `full_name`, `tax_id`, a `signer_role` of `OWNER`, `AUTHORIZED_SIGNER`, `POWER_OF_ATTORNEY`, `TRUSTEE`, or `BUSINESS_OFFICER`, and a `signature_card_reference` — requires that the reference equal the `reference_number` of a `VERIFIED` `SIGNATURE_CARD` document on the same account; without one the request fails with `ERR_DOCUMENTS_INCOMPLETE`. A signer starts `ACTIVE`.

Removal distinguishes staff initiative from cascades. An `OpsOfficer` or `OpsManager` may remove a signer: an `ACTIVE` signer can be removed while the account is not `CLOSED` — attempts against a closed account, or against a signer not currently `ACTIVE` or `SUSPENDED`, fail with `ERR_INVALID_STATE` — and a `SUSPENDED` signer can be removed as well; either way a manual removal stamps `removed_reason` with `STAFF_REQUEST`. The system itself moves signers twice: verifying a death report suspends every `ACTIVE` signer on the account (the cascade of §3.4, which leaves `removed_reason` untouched), and account closure removes every `ACTIVE` or `SUSPENDED` signer, stamping `removed_reason` with `DECEASED_CASCADE` when the closure is an estate release and `ACCOUNT_CLOSED` otherwise. `REMOVED` is terminal, and `removed_reason` stays null until then. Signers can be listed filtered by `status`.

### 3.3. Retitling an Account: Title Change Requests

Changing how an account is titled is a documented, two-person workflow. An `OpsOfficer` files a title change request naming the `requested_ownership_type` — which must differ from the account's current `ownership_type`, failing shape validation with `ERR_INVALID_REQUEST` otherwise — plus a `pod_beneficiary_name` when, and only when, the requested type is `POD`. Because retitling rewrites legal ownership, filing is optimistic-concurrency guarded per §2.11: the request must carry `expected_account_version` equal to the account's current `version`, and a mismatch rejects the filing with `ERR_STALE_VERSION` (HTTP 412), forcing the officer to re-read the account before proceeding.

The new request lands in `SUBMITTED`, snapshots the account's current type into `current_ownership_type`, records the filer in `created_by_user_id`, and registers against the account, bumping its `version`. The server derives `required_doc_types` from the requested type: a `POD` target demands a `POD_DESIGNATION`; a `TRUST` target a `TRUST_AGREEMENT`; a `BUSINESS` target both a `BUSINESS_RESOLUTION` and a `SIGNATURE_CARD`; and `INDIVIDUAL` and `JOINT` targets each demand a `SIGNATURE_CARD`. An account tolerates at most one `SUBMITTED` title change at a time — a second filing while one is in flight fails with `ERR_ACTIVE_REQUEST_EXISTS`.

Approval belongs to an `OpsManager` and is gated by four checks. The request must still be `SUBMITTED` (`ERR_INVALID_STATE` otherwise); the account must be `OPEN` with restriction `NONE` (`ERR_ACCOUNT_RESTRICTED` otherwise); every document type in `required_doc_types` must have a `VERIFIED` document on the account (`ERR_DOCUMENTS_INCOMPLETE` otherwise); and the approver's `X-User-ID` must differ from the filer's recorded in `created_by_user_id` — the segregation-of-duties rule, failing with `ERR_SEGREGATION_OF_DUTIES`. Approval applies the new title: the account's `ownership_type` becomes the requested type, `pod_beneficiary_name` is updated when the requested type is `POD`, the deciding manager is recorded in `decided_by_user_id`, and the account's `version` increments. `APPROVED` is terminal.

Rejection preserves the loop. A manager rejects a `SUBMITTED` request — any other status fails with `ERR_INVALID_STATE` — by supplying a `reason`, stored verbatim in `decision_reason` alongside the manager's identity in `decided_by_user_id`. The system also rejects in-flight requests on its own: death verification stamps `decision_reason` with `DECEASED_ACCOUNT`, and account closure stamps it with `ACCOUNT_CLOSED`, in both cases with no deciding user recorded. Rejection is not the end: an `OpsOfficer` may resubmit a `REJECTED` request, provided the account is `OPEN` with restriction `NONE` (`ERR_ACCOUNT_RESTRICTED` otherwise) and no other request is `SUBMITTED` on the account (`ERR_ACTIVE_REQUEST_EXISTS`); a request not currently `REJECTED` cannot be resubmitted (`ERR_INVALID_STATE`). Resubmission returns the request to `SUBMITTED`, recomputes `required_doc_types`, and clears `decision_reason` and `decided_by_user_id` — the reject-and-resubmit loop may repeat any number of times. Title change requests can be listed filtered by `status`.

### 3.4. Deceased-Account Handling and Estate Release

A death claim begins when an `OpsOfficer` reports a deceased owner with the `decedent_name`, the `date_of_death`, and the reporting party's name or capacity in `reported_by`. The date of death may not lie in the future relative to the logical clock (`ERR_DATE_RANGE_INVALID`), and an account carries at most one active case — in `REPORTED`, `VERIFIED`, or `RELEASE_PENDING` — at a time (`ERR_ACTIVE_REQUEST_EXISTS`). The case opens in `REPORTED`.

Verification is a manager's decision gated on proof of death. An `OpsManager` verifies a case still in `REPORTED` — any other status fails with `ERR_INVALID_STATE` — and only when the account holds a `VERIFIED` `DEATH_CERTIFICATE` document (`ERR_DOCUMENTS_INCOMPLETE` otherwise). Verification freezes the estate's basis: `balance_at_death_cents` snapshots the account's `balance_cents`, and `accrued_interest_at_death_cents` snapshots the interest accrued over the half-open window from `accrual_start_date` up to the `date_of_death`, computed with the STANDARD rounding variant regardless of the account's product; both stay null until this moment. The same act hardens the account: `restriction_status` moves from `NONE` to `DECEASED_HOLD`, every `ACTIVE` signer is suspended, every `SUBMITTED` title change is auto-rejected with `decision_reason` `DECEASED_ACCOUNT`, and `statement_suppression` recomputes to `DECEASED` — one mutation that increments the account's `version`.

Once the estate's authority is documented, an `OpsOfficer` initiates the release. Initiation requires the case to be `VERIFIED` (`ERR_INVALID_STATE` otherwise), a `VERIFIED` `LETTERS_TESTAMENTARY` document on the account (`ERR_DOCUMENTS_INCOMPLETE` otherwise), and no garnishment order still holding funds on the account (`ERR_CLOSURE_BLOCKED` otherwise) — the estate's money must be unencumbered before it is measured. The officer chooses a `release_variant` and names the `estate_representative_name`. Under `DATE_OF_DEATH`, funds are quarantined at death: `release_amount_cents` is the sum of `balance_at_death_cents` and `accrued_interest_at_death_cents`, excluding post-death deposits and later interest. Under `DATE_OF_RELEASE`, the estate receives everything through the release: `release_amount_cents` is the account's current `balance_cents` plus interest accrued under the STANDARD variant over the half-open window from `accrual_start_date` to the current logical clock date. Initiation records the officer in `initiated_by_user_id` and moves the case to `RELEASE_PENDING`; `release_amount_cents` and `initiated_by_user_id` stay null until then.

Approval completes the estate. An `OpsManager` approves a `RELEASE_PENDING` case (`ERR_INVALID_STATE` otherwise) provided the approver is not the officer who initiated it — the segregation-of-duties check, failing with `ERR_SEGREGATION_OF_DUTIES`. Approval posts an `ESTATE_RELEASE` transaction debiting `release_amount_cents`, then sweeps any residual: if the balance remains above zero — as it can when post-death credits landed under the `DATE_OF_DEATH` variant — a `CLOSURE_PAYOUT` transaction of the remaining balance posts. The account closes in the same atomic act: the `DECEASED_HOLD` restriction clears to `NONE` only as part of this estate-release closure, the lifecycle proceeds to `CLOSED`, `closure_payout_cents` is the release amount plus the residual swept, and `closure_payout_destination` is `ESTATE`. The conservation invariant holds through the whole act — the balance immediately before approval equals the release amount plus the residual, and the final balance is exactly zero. The standard closure cascade follows, with signers removed under `DECEASED_CASCADE`, submitted title changes rejected under `ACCOUNT_CLOSED`, scheduled conversions cancelled, and scheduled statement cycles suppressed under `CLOSED`; `approved_by_user_id` records the approving manager, null until then, and the account's `version` increments. `RELEASED` is terminal. Deceased cases can be listed filtered by `status`.

### 3.5. Garnishments, Levies, and Exempt-Funds Analysis

Legal process arrives through an `OpsOfficer`, who registers an order with an `order_type` of `GARNISHMENT`, `TAX_LEVY`, or `CHILD_SUPPORT`, the `creditor_name`, the claimed `amount_cents` (which must be positive), the `served_date`, and an `exemption_method` of `FEDERAL_LOOKBACK` or `STATE_MINIMUM`. Service cannot be future-dated: a `served_date` after the logical clock date is rejected with `ERR_DATE_RANGE_INVALID`. The server computes the `answer_deadline_date` as twenty calendar days after the served date, and the order's closed service window — from `served_date` through `answer_deadline_date`, both days inclusive — must not overlap the service window of any other order still holding funds on the account; a conflict is rejected with `ERR_LEGAL_ORDER_WINDOW_CONFLICT`.

Registration acts atomically. The hold is placed at receipt: `held_amount_cents` is the lesser of the claimed amount and the account's `available_balance_cents` at that moment, the receiving officer is recorded in `received_by_user_id`, and the order enters `FUNDS_HELD` while the account's restriction moves from `NONE` to `LEGAL_HOLD` — the account totals recompute and its `version` increments inside the same mutation.

The exempt-funds analysis runs in that same atomic step. The lookback window is the closed sixty-day interval ending on the served date — from sixty days before `served_date` through `served_date` inclusive — and the benefit total is the sum of `amount_cents` over the account's `FEDERAL_BENEFIT_DEPOSIT` transactions whose `posted_date` falls inside that window; every other transaction type is excluded. Under `FEDERAL_LOOKBACK`, `exempt_amount_cents` is the lesser of the account's ledger balance and the benefit total, with no floor. Under `STATE_MINIMUM`, `exempt_amount_cents` is the lesser of the ledger balance and the greater of a statutory floor of 100000 cents (one thousand dollars) and the benefit total — the floor protects a full thousand dollars even when benefit deposits are smaller. `collectible_cents` is then the held amount minus the exempt amount, never below zero. All figures are integer cents with no rounding.

Resolution belongs to an `OpsManager` and forks into two branches, each specified fully. The order must still be `FUNDS_HELD` (`ERR_INVALID_STATE` otherwise), and the resolver must not be the officer recorded in `received_by_user_id` (`ERR_SEGREGATION_OF_DUTIES` otherwise). Remitting — a `resolution` of `REMITTED` — additionally requires the answer period to have elapsed: the logical clock date must be strictly after `answer_deadline_date`, failing with `ERR_ANSWER_PERIOD_NOT_ELAPSED` otherwise. The remitted amount defaults to `collectible_cents`; an explicit `remit_amount_cents` override is accepted only up to `collectible_cents` (`ERR_AMOUNT_EXCEEDS_COLLECTIBLE` beyond it). Remittance posts a `LEGAL_REMITTANCE` debit for the remitted amount, records it in `remitted_amount_cents`, and returns the rest of the hold, recording `released_amount_cents` as the held amount minus the remitted amount. Releasing — a `resolution` of `RELEASED` — posts no ledger transaction at all: the entire hold is returned, so `released_amount_cents` equals `held_amount_cents` and `remitted_amount_cents` stays zero. Either branch records the resolver in `resolved_by_user_id`, subtracts the hold from `total_held_cents`, recomputes `available_balance_cents`, returns the account's restriction to `NONE` when no order remains in `FUNDS_HELD`, and increments the account's `version`. `REMITTED` and `RELEASED` are both terminal, `remitted_amount_cents` is zero until remittance, and `released_amount_cents` is zero until resolution. Garnishment orders can be listed filtered by `status`.

### 3.6. Statement Cycles: Production and Suppression

Statement production is scheduled ahead. An `OpsOfficer` or the `System` principal schedules a cycle with a `cycle_start` and a `cycle_end`, defining a half-open period that begins on `cycle_start` and ends just before `cycle_end`; an end that does not fall strictly after the start fails shape validation with `ERR_INVALID_REQUEST`. Cycles on the same account may touch but never overlap: a new period that shares any day with an existing cycle is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`, while a cycle starting exactly on another cycle's end date is lawful adjacency. A fresh cycle is `SCHEDULED` with `produced_date` null and `suppression_reason` null.

The daily sweep settles cycles whose `cycle_end` has arrived, meaning it falls on or before the sweep date. When the account's `statement_suppression` is `NONE`, the cycle is `PRODUCED` and `produced_date` takes the sweep date. When suppression is anything other than `NONE`, the cycle is `SUPPRESSED` instead: `suppression_reason` records the posture class — `DORMANT`, `DECEASED`, or `CLOSED` — and `produced_date` still takes the sweep date. Account closure suppresses any still-scheduled cycles as part of the closure cascade, stamping `suppression_reason` `CLOSED` and `produced_date` with the closure date. `PRODUCED` and `SUPPRESSED` are both terminal. Statement cycles can be listed filtered by `status`.

### 3.7. Rate and Product Conversions

Repricing is scheduled, never retroactive. An `OpsOfficer` schedules a conversion with a `to_product_code` that differs from the account's current product — failing shape validation with `ERR_INVALID_REQUEST` otherwise — a `new_rate_bps` between 0 and 2000 inclusive, and an `effective_date` that lies strictly after the current logical clock date (`ERR_EFFECTIVE_DATE_NOT_FUTURE` otherwise). The request snapshots today's product into `from_product_code` and lands in `SCHEDULED`, and an account carries at most one scheduled conversion at a time (`ERR_ACTIVE_REQUEST_EXISTS`).

Execution applies what was scheduled. An `OpsOfficer` or the `System` principal executes a conversion still in `SCHEDULED` — any other status fails `ERR_INVALID_STATE` — once the logical clock date reaches the `effective_date`; executing earlier fails with `ERR_CONVERSION_NOT_DUE`. The account must still be operable: its lifecycle must be `OPEN`, `DORMANT`, or `ESCHEAT_PENDING` (`ERR_INVALID_STATE` for a closed account) and its restriction must not be `DECEASED_HOLD` (`ERR_ACCOUNT_RESTRICTED`); an ordinary legal hold does not stop a conversion. Execution first settles the old regime: interest accrued over the half-open window from `accrual_start_date` to `effective_date`, computed under the old product's rounding variant, posts as an `INTEREST_CREDIT` transaction and is recorded in `accrued_interest_settled_cents`, which stays null until that moment. Then the account's `product_code` becomes `to_product_code`, its `rate_bps` becomes `new_rate_bps`, and its `accrual_start_date` resets to `effective_date` so the new rate accrues from that day forward — one mutation that increments the account's `version` and completes the conversion. `COMPLETED` is terminal, and the only other exit from `SCHEDULED` is account closure, which cancels the conversion; there is no manual cancellation. Conversions can be listed filtered by `status`.

### 3.8. Dormancy, Inactivity Fees, and the Daily Sweep

Inactivity is measured in whole calendar days from `last_customer_activity_date`. The daily sweep — runnable by an `OpsManager` or the `System` principal against the current logical clock date — evaluates every account not yet `CLOSED`. An `OPEN` account inactive for at least 365 days becomes `DORMANT`, and the boundary is inclusive: exactly 365 days of inactivity qualifies. A `DORMANT` account inactive for at least 1095 days advances to `ESCHEAT_PENDING`; that transition recomputes `statement_suppression`, which remains in the `DORMANT` class, and increments the account's `version`. An `ESCHEAT_PENDING` account inactive for at least 1125 days is closed by escheat, described in §3.9.

Entering dormancy is itself an event. The account stamps `dormant_since_date` with the current date, leaves `fees_assessed_count` untouched because the episode continues, recomputes `statement_suppression`, immediately assesses the episode's first inactivity fee, and increments its `version`.

Fees follow a pinned schedule. The dormancy entry transition assesses fee number one. On every later sweep, the number of fees that should have been assessed in the current episode is pinned as one plus the count of complete thirty-day periods elapsed between `dormant_since_date` and the sweep date, partial periods discarded. The fees due now are that target minus `fees_assessed_count`, never less than zero, and they post sequentially: each fee is the lesser of 500 cents and the balance at that instant, posts as an `INACTIVITY_FEE` transaction, and increments `fees_assessed_count`. A fee that computes to zero is never posted, and posting stops there — fees never overdraw the account. When a fee run drains the balance to exactly zero on an account still `DORMANT`, the sweep closes the account automatically: the zero-balance auto-close of §3.9.

The sweep also runs statement production and suppression for due cycles, per §3.6, and reports its own tallies: `evaluated_accounts`, `newly_dormant`, `fees_assessed_count`, `fees_assessed_cents`, `auto_closed_count`, `escheated_count`, `statements_produced`, and `statements_suppressed`.

### 3.9. Account Closure and Residual Payouts

Closure is deliberate, guarded, and final. An `OpsOfficer` or `OpsManager` closes an account in `OPEN`, `DORMANT`, or `ESCHEAT_PENDING` — an already-`CLOSED` account fails with `ERR_INVALID_STATE`. Closure is optimistic-concurrency guarded per §2.11: the request must carry `expected_account_version` matching the account's current `version`, because intervening mutations change the residual payout basis, and a stale presentation is rejected with `ERR_STALE_VERSION` (HTTP 412). Closure is also barred while legal or transitional work is in flight: the restriction must be `NONE` with no garnishment in `FUNDS_HELD`, no deceased case in `REPORTED`, `VERIFIED`, or `RELEASE_PENDING`, and no title change in `SUBMITTED` — any of these rejects with `ERR_CLOSURE_BLOCKED`.

A manual closure settles interest accrued over the half-open window from `accrual_start_date` to the close date, under the account's product rounding variant, posting it as an `INTEREST_CREDIT` transaction; a `CLOSURE_PAYOUT` transaction then drains the balance to exactly zero. The account records `closure_payout_cents` as the pre-close balance plus the settled interest and `closure_payout_destination` as `OWNER`, and its `version` increments.

Two sweep paths close accounts on their own, with the same cascade but different payouts. Escheat closure — an `ESCHEAT_PENDING` account reaching 1125 inactive days — settles interest the same way, then drains the balance as a `CLOSURE_PAYOUT`; here `closure_payout_cents` is the balance plus the settled interest and the destination is `STATE_ESCHEAT`. Zero-balance auto-close — a `DORMANT` account whose fee run leaves the balance at exactly zero — records `closure_payout_cents` of zero with destination `OWNER`. The estate-release approval of §3.4 is the fourth closure path, paying the estate under destination `ESTATE`.

Every closure runs the same cascade over the account's children: every `ACTIVE` or `SUSPENDED` signer is `REMOVED` with `removed_reason` `ACCOUNT_CLOSED` (or `DECEASED_CASCADE` when the closure is an estate release); every `SUBMITTED` title change is `REJECTED` with `decision_reason` `ACCOUNT_CLOSED`; every `SCHEDULED` product conversion is `CANCELLED`; and every `SCHEDULED` statement cycle is `SUPPRESSED` with reason `CLOSED`. `CLOSED` is terminal and ends all account activity.

## 4. Endpoint Definitions

Operations that create a new resource — opening an account, posting a transaction, adding a signer, submitting a document, filing a title change, reporting a death, registering a garnishment, scheduling a statement cycle or a conversion — return `201 Created`. Operations that act on an existing resource without creating one — closures, reviews, approvals, rejections, resubmissions, removals, resolutions, executions, the daily sweep, and the clock set — return `200 OK`. All endpoints are mounted under `/bank`. The table below states only the HTTP contract; request fields, preconditions, and side effects are defined by the narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/bank/accounts` | Open a deposit account; posts the opening deposit as a customer-initiated transaction | OpsOfficer, OpsManager |
| GET    | `/bank/accounts` | List accounts with pagination and filters | OpsOfficer, OpsManager, Auditor, System |
| GET    | `/bank/accounts/{id}` | Get one account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/close` | Close an account: settle accrued interest, drain the residual as closure payout, run the closure cascade; OCC-guarded | OpsOfficer, OpsManager |
| POST   | `/bank/accounts/{id}/transactions` | Post a customer-facing transaction; customer-initiated postings reactivate dormant or escheat-pending accounts | OpsOfficer, System |
| GET    | `/bank/accounts/{id}/transactions` | List transactions of an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/signers` | Add an authorized signer against a verified signature card | OpsOfficer |
| POST   | `/bank/signers/{signerId}/remove` | Remove a signer (reason STAFF_REQUEST) | OpsOfficer, OpsManager |
| GET    | `/bank/accounts/{id}/signers` | List signers of an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/documents` | Submit a document onto an account | OpsOfficer |
| POST   | `/bank/documents/{documentId}/review` | Review a submitted document (VERIFIED or REJECTED) | OpsManager |
| GET    | `/bank/accounts/{id}/documents` | List documents on an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/title-changes` | File a title change request; OCC-guarded; computes required document types | OpsOfficer |
| POST   | `/bank/title-changes/{requestId}/approve` | Approve a title change; cannot be the creator; applies the new ownership type | OpsManager |
| POST   | `/bank/title-changes/{requestId}/reject` | Reject a title change with a reason | OpsManager |
| POST   | `/bank/title-changes/{requestId}/resubmit` | Resubmit a REJECTED title change back to SUBMITTED | OpsOfficer |
| GET    | `/bank/accounts/{id}/title-changes` | List title change requests of an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/deceased-cases` | Report a deceased account owner | OpsOfficer |
| POST   | `/bank/deceased-cases/{caseId}/verify` | Verify a death report; snapshots balances and cascades the deceased restriction | OpsManager |
| POST   | `/bank/deceased-cases/{caseId}/initiate-release` | Initiate estate release; computes the release amount per variant | OpsOfficer |
| POST   | `/bank/deceased-cases/{caseId}/approve-release` | Approve estate release; cannot be the initiator; debits the release and closes the account to the estate | OpsManager |
| GET    | `/bank/accounts/{id}/deceased-cases` | List deceased cases of an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/garnishments` | Register a garnishment or levy; places the hold atomically and runs the exempt-funds analysis | OpsOfficer |
| POST   | `/bank/garnishments/{orderId}/resolve` | Resolve a held order by remitting or releasing; resolver cannot be the receiver | OpsManager |
| GET    | `/bank/accounts/{id}/garnishments` | List garnishment orders of an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/statement-cycles` | Schedule a statement cycle; overlapping periods rejected, adjacency allowed | OpsOfficer, System |
| GET    | `/bank/accounts/{id}/statement-cycles` | List statement cycles of an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/accounts/{id}/conversions` | Schedule a rate/product conversion with a future effective date | OpsOfficer |
| POST   | `/bank/conversions/{conversionId}/execute` | Execute a due conversion: settle old-product accrued interest, apply the new product and rate | OpsOfficer, System |
| GET    | `/bank/accounts/{id}/conversions` | List conversions of an account | OpsOfficer, OpsManager, Auditor, System |
| POST   | `/bank/ops/daily-sweep` | Run the nightly ops pass: dormancy evaluation, inactivity fees, zero-balance and escheat closures, statement production and suppression | OpsManager, System |
| POST   | `/bank/_clock/set_current_utc` | Set the server's logical UTC clock | OpsManager, System |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ACCOUNT_RESTRICTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_CLOSURE_BLOCKED` | 409 Conflict |
| `ERR_DOCUMENTS_INCOMPLETE` | 409 Conflict |
| `ERR_ACTIVE_REQUEST_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_REFERENCE` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_LEGAL_ORDER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DATE_RANGE_INVALID` | 409 Conflict |
| `ERR_EFFECTIVE_DATE_NOT_FUTURE` | 409 Conflict |
| `ERR_CONVERSION_NOT_DUE` | 409 Conflict |
| `ERR_ANSWER_PERIOD_NOT_ELAPSED` | 409 Conflict |
| `ERR_INSUFFICIENT_AVAILABLE_FUNDS` | 409 Conflict |
| `ERR_AMOUNT_EXCEEDS_COLLECTIBLE` | 409 Conflict |
