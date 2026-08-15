# Stock Transfer Agent API — Product Requirements Document

## 1. Introduction

Every issuer of registered securities depends on a transfer agent to maintain the definitive record of who owns its shares. This document specifies the Stock Transfer Agent API: a shareholder recordkeeping platform in the style of a Computershare-class transfer agent, covering the full registrar workload — registered holder records and book-entry (DRS) positions, physical certificate issuance and cancellation, transfer request review under medallion signature guarantee, lost certificate claims secured by indemnity bonds, cash dividend declaration and disbursement with tax withholding, restricted-stock legend removal, escheatment of unclaimed shares and dividends to the states, shareholder inquiries and statements, and issuer reporting including the record-date holder list.

The platform is built for regulated operations. Seven operator roles interact under explicit segregation of duties, every mutation is chained into a tamper-evident audit log, and time-driven processing — record-date accrual, disbursement, stale-dating of uncashed checks, freeze-window activation, dormancy sweeps — is governed by a controllable logical clock rather than wall-clock time, so that compliance timelines can be exercised deterministically. Two sensitive creation flows are guarded by optimistic concurrency tokens. This document is the complete functional specification for the service: Section 2 defines the wire contract and system-wide principles, Section 3 walks the business workflows those primitives must support, and Sections 4 and 5 tabulate the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold for every resource and every request in the system, independent of any particular workflow.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly seven roles: `AgentAdmin`, `Shareholder`, `TransferExaminer`, `TransferSupervisor`, `IssuerOfficer`, `ComplianceOfficer`, and `ServiceAgent`. A request with missing headers, or whose `X-User-Role` is not one of these declared role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the endpoint it targets — or a `Shareholder` attempting to act on another holder's resources — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Shareholder`, `X-User-ID` is the `id` of the acting `ShareholderAccount`; ownership checks on any resource that references a `ShareholderAccount` compare the resource's foreign-key field to `X-User-ID` — the `from_account_id` of a transfer request being submitted or cancelled, the `account_id` of an account, inquiry, or legend-removal request, or the `account_id` of the dividend payment being cashed. When `X-User-Role` is `IssuerOfficer`, `X-User-ID` is the `id` of the acting `Issuer`; ownership checks on any resource that references an `Issuer` compare the resource's `issuer_id` field to `X-User-ID`.

The remaining five roles carry opaque operator identifiers not tied to any persisted entity; the server may record such an identifier where a workflow writes it, but never compares it to any entity's `id`. When `X-User-Role` is `AgentAdmin`, the identifier is opaque platform-operator identity. When `X-User-Role` is `TransferExaminer`, the identifier is opaque; the server records it as `last_examiner_id` on a `TransferRequest` the examiner verifies or flags, and as `filed_by_examiner_id` on a `LostCertificateClaim` the examiner files, but does not compare it to any entity's `id`. When `X-User-Role` is `TransferSupervisor`, the identifier is opaque; the server records it as `approved_by` on an approved `TransferRequest`. When `X-User-Role` is `ComplianceOfficer`, the identifier is opaque. When `X-User-Role` is `ServiceAgent`, the identifier is opaque; the server records it as `claimed_by_agent_id` on a `ShareholderInquiry` the agent claims.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, so clients can page deterministically through the register.

### 2.4. The Logical Clock and Time-Gated Processing

The platform never consults wall-clock time. Every time-dependent rule in this document — dormancy anniversaries, record dates, payable dates, stale-dating horizons, freeze windows, holding periods — is evaluated against a single logical clock maintained by the server. Before the clock has ever been set, its value is exactly `2026-08-01T00:00:00Z`; the clock never falls back to wall-clock time. An `AgentAdmin` advances the clock through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. Each time the clock is set, the server evaluates every time-gated system transition at the new instant: dividend declarations whose `record_date` has been reached are accrued, accrued declarations whose `payable_date` has been reached become payable and disburse their payments, disbursed payments that have sat uncashed for the full stale-dating horizon become stale-dated, and freeze windows activate once their `start_date` is reached and expire once the clock has passed their `end_date`. Every system-assigned timestamp in the domain — a certificate's `issued_at` or `lost_reported_at`, a transfer's `settled_at`, a payment's `disbursed_at` or `returned_at`, a case's `notice_sent_at`, and every refresh of an account's `last_qualifying_contact_date` — is written from this logical clock.

### 2.5. Common Resource Properties

Every primary resource in the system — issuers, accounts, positions, certificates, transfer requests, claims, declarations, payments, legend-removal requests, escheatment cases, inquiries, and freeze windows — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example `2025-05-24T10:30:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, and that anchors the optimistic concurrency rules of §2.7.

The `AuditEvent` resource is the single exception to this convention. Audit events are append-only and immutable: an `AuditEvent` carries only `id` and `created_at` from the standard set, and both `updated_at` and `version` are absent from it.

### 2.6. Monetary Precision and Rounding

All monetary amounts in the system are represented as integer cents — prices such as `current_market_price_cents` and `par_value_cents`, valuations such as `transfer_value_cents` and `bond_amount_cents`, and payment amounts such as `gross_cents`, `withholding_cents`, and `net_cents` are all whole numbers of cents. The single exception in scale is the declared dividend rate, which is expressed in millicents: one thousand millicents make one cent, so `amount_per_share_millicents` allows an issuer to declare fractional-cent dividends. Whenever a calculation crosses from millicents to cents, or produces a fractional cent, the result is rounded half-up to the nearest whole cent — a remainder of exactly half a cent rounds away from zero. Rounding is always applied per payment, at the boundary where the payment's amount is fixed, never once over an aggregate; §3.5 pins the exact evaluation order. No monetary value is ever stored or returned as a floating-point number.

### 2.7. Optimistic Concurrency Control

Two creation endpoints carry an optimistic concurrency token, because both touch an aggregate whose balance of open work is tracked by a counter on a parent resource.

Creating a transfer request requires the client to supply `expected_account_version`, carrying the `version` of the transferor's `ShareholderAccount` as the client last observed it. If the account's current `version` no longer matches — for example because another transfer was opened against the same account, or an earlier transfer reached a terminal state, in each case moving `pending_transfer_count` and advancing the account's `version` — the creation is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). The client must re-read the account and resubmit with the current version.

Creating a legend-removal request requires the client to supply `expected_position_version`, carrying the `version` of the target `Position` as the client last observed it. If the position's current `version` no longer matches — for example because an earlier legend removal was approved and `restricted_shares` changed, or another request was opened against the same position — the creation is rejected with `ERR_STALE_POSITION_VERSION` (HTTP 412), and the client must re-read the position before resubmitting.

No endpoint other than these two creations accepts a version token; all other mutations are applied against the server's current state without an optimistic check.

### 2.8. Validation Order and Nested Path Resolution

Every request is validated against a fixed cascade of checks, evaluated in the following order, and the first failing check determines the error returned:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present, and the role must be one of the seven declared roles; failures yield `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership.** The presented role must be authorized for the endpoint, and a `Shareholder` caller's `X-User-ID` must equal the account that owns the acted-on resource; failures yield `ERR_UNAUTHORIZED_ROLE`.
3. **Existence.** Path identifiers are resolved strictly from left to right, and the request is rejected with the specific 404 for the leftmost segment that does not resolve — `ERR_ISSUER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DECLARATION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_LEGEND_REQUEST_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, or `ERR_INQUIRY_NOT_FOUND` — before any later segment is even considered. Identifiers referenced in a request body resolve at the same stage: an unresolvable `issuer_id` in a payload yields `ERR_ISSUER_NOT_FOUND`, and a transfer request naming an account and security for which no position has been seeded yields `ERR_POSITION_NOT_FOUND`.
4. **Optimistic concurrency.** On the two guarded creations of §2.7, a stale token yields `ERR_STALE_ACCOUNT_VERSION` or `ERR_STALE_POSITION_VERSION`.
5. **State gates.** The target resource must be in a from-state the invoked transition permits, and related-entity state gates are enforced: transfer creation against a `RESTRICTED` account fails with `ERR_ACCOUNT_RESTRICTED`; any mutation targeting an `ESCHEATED` account fails with `ERR_ACCOUNT_ESCHEATED`; transfer creation or dividend declaration while the issuer is `SUSPENDED` fails with `ERR_ISSUER_SUSPENDED`; settling or depositing a certificate under a stop-transfer order fails with `ERR_CERTIFICATE_STOPPED`; reissuing a payment to an unverified address fails with `ERR_ADDRESS_UNVERIFIED`; and any other transition attempted from an impermissible state fails with the generic `ERR_INVALID_STATE`.
6. **Segregation of duties.** Approval of an item by the same operator who examined or filed it fails with `ERR_SEGREGATION_OF_DUTIES`; this gate applies to transfer approval and to lost-certificate claim approval.
7. **Temporal gates.** Settlement inside an issuer freeze window fails with `ERR_TRANSFER_FREEZE_CONFLICT`; malformed date ranges fail with `ERR_INVALID_DATE_RANGE`; legend approval before the holding period has elapsed fails with `ERR_HOLDING_PERIOD_NOT_MET`; and reporting an escheatment case before the due-diligence window has elapsed fails with `ERR_NOTICE_WINDOW_NOT_ELAPSED`.
8. **Uniqueness and request shape.** A duplicate `cusip` fails with `ERR_DUPLICATE_CUSIP`; a second position for the same account and issuer fails with `ERR_DUPLICATE_POSITION`; a lost report on a certificate that already has an open claim fails with `ERR_DUPLICATE_OPEN_CLAIM`; an overlapping freeze window fails with `ERR_FREEZE_WINDOW_OVERLAP`; a share quantity below one fails with `ERR_ZERO_SHARE_QUANTITY`; and missing required fields, malformed values, or enum values outside their declared sets fail with `ERR_INVALID_REQUEST`.
9. **Cross-reference consistency.** A referenced position or certificate that does not belong to the named account — or, for a certificated transfer source, to the named issuer — fails with `ERR_POSITION_ACCOUNT_MISMATCH`.
10. **Fund and share sufficiency, always checked last.** Insufficient book-entry shares for a transfer or certificate withdrawal fail with `ERR_INSUFFICIENT_SHARES`; a legend-removal quantity exceeding the restricted balance fails with `ERR_INSUFFICIENT_RESTRICTED_SHARES`; an under-tendered bond premium fails with `ERR_BOND_PREMIUM_INSUFFICIENT`; and an under-covered medallion stamp fails with `ERR_MEDALLION_COVERAGE_INSUFFICIENT`.

Because the cascade is ordered, a request that would fail several gates always surfaces the earliest one. A transfer creation against a restricted account whose position is also short of shares is rejected with `ERR_ACCOUNT_RESTRICTED`, never with the sufficiency code; a medallion submission by an unauthorized role is rejected with `ERR_UNAUTHORIZED_ROLE` before its coverage amount is ever examined.

### 2.9. The Tamper-Evident Audit Chain

Every mutation in the system appends an `AuditEvent` to a hash-chained, append-only log. Each event records `entity_type` — the polymorphic type name of the mutated resource, such as `TransferRequest` — and `entity_id`, the identifier of the mutated resource, which is deliberately not a foreign key since events may target any entity in the system. The `actor_role` and `actor_id` fields are copied from the request's `X-User-Role` and `X-User-ID` headers. The `action` field carries the endpoint's action label, for example `transfer.settle` or `issuer.suspend`. The `from_state` records the resource's state before the transition — left empty for creations — and `to_state` records the state after. A free-form `detail` summarizes the mutation. Tamper evidence comes from two hash fields: `prev_entry_hash` is the SHA-256 of the previous event in the chain, or the literal value `GENESIS` for the first entry, and `entry_hash` is the SHA-256 computed over `prev_entry_hash` together with the event's canonical fields, so any retroactive edit breaks the chain. The chain is queryable by `AgentAdmin` and `ComplianceOfficer` through a filtered listing accepting optional `entity_type` and `entity_id` parameters.

### 2.10. Share Conservation and Issuer-Level Totals

An issuer's `shares_outstanding` is the conservation anchor of the whole register: at onboarding it declares the total issued shares of the security, and the sum of the shares seeded into holder positions for that issuer must equal it. Each position divides its holding between two forms — `book_entry_shares` held in uncertificated DRS form and `certificated_shares` held in physical certificate form — and exposes `total_shares` as the sum of the two. Within the book-entry leg, `restricted_shares` counts the subset carrying a restrictive legend; it may never be negative and may never exceed the position's `book_entry_shares`. Every issuer in turn exposes two computed aggregates, `total_book_entry_shares` and `total_certificated_shares`, which sum the corresponding legs across all of the issuer's positions. These aggregates are not stored inputs: they are recomputed from the positions whenever any flow moves shares — position seeding, certificate withdrawal or deposit, transfer settlement, or escheatment remittance — so the issuer-level view can never drift from the holder-level register.

## 3. Business Logic & Workflows

### 3.1. Issuer Onboarding, Holder Registration, and Positions

Before any holder activity can occur, an `AgentAdmin` onboards the security itself. Creating an issuer captures its legal `name`, its nine-character `cusip`, its exchange `ticker`, the total `shares_outstanding` that anchors conservation, an optional `par_value_cents` that defaults to zero, and the `current_market_price_cents` that later feeds transfer valuation, bond calculation, and escheatment reporting. A `cusip` is unique across all issuers: registering a security whose `cusip` is already on the platform is refused with `ERR_DUPLICATE_CUSIP`. A newly onboarded issuer begins life `ACTIVE`, and the creation is recorded in the audit chain under the action `issuer.create`.

From that point on, an `IssuerOfficer` acting for the security maintains its trading data. The officer may patch the `current_market_price_cents` as the market moves, and may suspend the security by setting its `status` to `SUSPENDED` or resume it by returning to `ACTIVE`; suspension is only possible while the issuer is `ACTIVE`, and resumption only while it is `SUSPENDED`. Every such patch increments the issuer's `version` by one and refreshes its `updated_at`, and suspensions and resumptions are audited as `issuer.suspend` and `issuer.resume` respectively, with other patches audited as `issuer.patch`. Reading an issuer returns the record together with its computed `total_book_entry_shares` and `total_certificated_shares`.

An officer may also declare a **transfer freeze window** over the security — a closed interval of days during which no transfer of the security may settle. The declaration supplies a `start_date` (the first frozen day, inclusive), an `end_date` (the last frozen day, inclusive), and a free-text `reason`, and the window enters the register in `SCHEDULED` status; the creation is audited as `freeze.create`. An `end_date` earlier than the `start_date` is rejected with `ERR_INVALID_DATE_RANGE`, while a window whose end equals its start describes a valid single-day freeze. Windows on the same issuer may not overlap: a new window conflicts with any existing window that has not yet reached `EXPIRED` status whenever the new window's `start_date` falls on or before the existing window's `end_date` and the existing window's `start_date` falls on or before the new window's `end_date` — closed-interval semantics under which two windows sharing even a single boundary day conflict — and such a declaration is refused with `ERR_FREEZE_WINDOW_OVERLAP`. The logical clock then drives the window's lifecycle without further operator action: when the clock reaches the `start_date` the window moves `SCHEDULED` → `ACTIVE`, and once the clock passes the `end_date` it moves `ACTIVE` → `EXPIRED` and never blocks settlement again.

Holder onboarding is likewise an `AgentAdmin` function. Registering a shareholder account captures the registered holder's legal `holder_name` and full mailing address — `address_line1`, `city`, the two-letter `state_code` of residence, `postal_code`, and the ISO `country_code` — together with the holder's `tax_id` as provided. Three tax attributes ride on the account: `residency`, which is `US` or `FOREIGN` and defaults to `US` when omitted; `tin_status`, the W-9 certification status, which is one of `MISSING`, `CERTIFIED`, or `UNCERTIFIED` and defaults to `MISSING`; and `treaty_tier`, which is `STANDARD` or `TREATY`, defaults to `STANDARD`, and only bears on withholding when the `residency` is `FOREIGN`. A new account's `account_status` begins at `ACTIVE` — the lifecycle later spans `RESTRICTED`, `DORMANT`, and the terminal `ESCHEATED` — its `address_verified` flag starts out true, its `pending_transfer_count` and `stale_dividend_cents` counters start at zero, and its `last_qualifying_contact_date` is initialized to the account's `created_at`. The `state_code` also determines the account's computed `dormancy_years`, the per-state abandonment horizon described in §3.7. Registration is audited as `account.create`.

Address and tax maintenance afterwards is a qualifying owner contact. A `Shareholder` patching their own account — or an `AgentAdmin` patching any account — may update any of `address_line1`, `city`, `state_code`, `postal_code`, `country_code`, `tin_status`, or `treaty_tier`. Every such patch sets `address_verified` back to true, refreshes `last_qualifying_contact_date` to the logical clock, increments the account's `version` by one, and — when the account was `DORMANT` — brings the account back `DORMANT` → `ACTIVE` with the escheatment-case reactivation cascade of §3.7.

A `ComplianceOfficer` can place a legal-hold restriction on an account, moving it `ACTIVE` → `RESTRICTED`, and can later lift the hold, moving it `RESTRICTED` → `ACTIVE`; both actions increment the account's `version` by one and are audited as `account.restrict` and `account.release`. Restriction has two systemic consequences developed later: a `RESTRICTED` account cannot be the source of a new transfer request (§3.3), and a `RESTRICTED` account is never swept into dormancy (§3.7).

With an issuer onboarded and an account registered, an `AgentAdmin` seeds the holder's registered position in that security by posting a payload containing the `issuer_id`, the opening `book_entry_shares`, and an optional `restricted_shares` count that defaults to zero. There is exactly one position per account-and-issuer pair: seeding a second position for the same pair is refused with `ERR_DUPLICATE_POSITION`. The seeded `restricted_shares` must stay within the book-entry leg — never negative, never greater than `book_entry_shares` — and the new position starts `ACTIVE` with `certificated_shares` at zero and `pending_legend_removal_count` at zero. Seeding recomputes the issuer's `total_book_entry_shares` and `total_certificated_shares`, and is audited as `position.create`. Positions can be listed with optional `account_id` and `issuer_id` filters, read per account, or read per issuer.

### 3.2. Certificate Form: Withdrawals and Deposits

Registered holders may hold shares in either form, and moving book-entry shares into physical certificate form is a `TransferExaminer` operation. The examiner submits the `share_quantity` to withdraw and may note whether the certificate bears a restrictive legend via the optional `legend_restricted` flag, which defaults to false. The request is refused with `ERR_ZERO_SHARE_QUANTITY` when the `share_quantity` is below one, and with `ERR_INSUFFICIENT_SHARES` when it exceeds the position's `book_entry_shares`. On success the position's `book_entry_shares` decreases by the withdrawn quantity, its `certificated_shares` increases by the same amount, the position's `version` increments by one, and the issuer's totals are recomputed. The minted certificate is `ISSUED`, carries a server-generated `certificate_number`, an `issued_at` timestamp taken from the logical clock, and `account_id` and `issuer_id` values copied from the position at withdrawal.

Deposit runs in the other direction. An examiner converting a certificate back to book-entry form requires the certificate to be `ISSUED`; the operation moves it `ISSUED` → `CANCELLED`, shifts its face quantity from the position's `certificated_shares` back into `book_entry_shares`, increments the position's `version`, and recomputes the issuer's totals. A certificate under a stop-transfer order is in `LOST_REPORTED` status and cannot be deposited: attempting the conversion is refused with `ERR_CERTIFICATE_STOPPED`, because the stop order must be resolved first (§3.4). A certificated-source transfer settlement cancels a certificate through the same machinery, as described in §3.3.

Certificates can be listed with optional `account_id`, `issuer_id`, and `status` filters, and per-account or per-issuer listings are also available.

### 3.3. Transfer Requests: Review, Guarantee, and Settlement

A transfer of record ownership begins when a `Shareholder` — the transferor, whose `X-User-ID` must equal the `from_account_id` — or a `TransferExaminer` acting on a holder's behalf submits a transfer request. The payload names the `from_account_id`, the `to_account_id`, the `issuer_id` of the security, and the `share_quantity` to move, and it carries the optimistic-concurrency token `expected_account_version` described in §2.7. A transfer out of physical certificates also names the `source_certificate_id`; a book-entry DRS transfer omits it. At creation the request's `transfer_value_cents` is frozen once and for all as the `share_quantity` multiplied by the issuer's `current_market_price_cents` at that moment, and the request enters `UNDER_REVIEW` status. Opening the request increments the transferor account's `pending_transfer_count` by one and advances the account's `version` by one — this is exactly the movement the next creator's `expected_account_version` must observe — and the creation is audited as `transfer.create`.

Creation is gated by the account, issuer, and share availability. A transfer out of a `RESTRICTED` account is refused with `ERR_ACCOUNT_RESTRICTED`, and any mutation aimed at an `ESCHEATED` account is refused with `ERR_ACCOUNT_ESCHEATED`. A transfer in a `SUSPENDED` security is refused with `ERR_ISSUER_SUSPENDED`. When no position exists for the transferor account and the named issuer, creation fails with `ERR_POSITION_NOT_FOUND`. A `share_quantity` below one is refused with `ERR_ZERO_SHARE_QUANTITY`. For a DRS transfer, a `share_quantity` exceeding the source position's `book_entry_shares` is refused with `ERR_INSUFFICIENT_SHARES`. For a certificated transfer, the `source_certificate_id` must name a certificate registered to the `from_account_id` and issued for the security named by `issuer_id` — a certificate belonging to a different account or a different issuer is refused with `ERR_POSITION_ACCOUNT_MISMATCH` — and the `share_quantity` must equal the certificate's face quantity exactly, partial certificate transfers being rejected as `ERR_INVALID_REQUEST`.

Review is the `TransferExaminer`'s desk. Submitting the medallion signature guarantee — a payload carrying the `medallion_reference` and the stamp's `coverage_cents` — moves the request `UNDER_REVIEW` → `MEDALLION_VERIFIED`, but only when the surety coverage is at least the frozen `transfer_value_cents`; a stamp covering even one cent less is refused with `ERR_MEDALLION_COVERAGE_INSUFFICIENT`, while coverage exactly equal to the transfer value suffices. The stamp's particulars are recorded on the request, the coverage landing in the stored `medallion_coverage_cents` field, and the examiner's identifier is written to `last_examiner_id`; the verification is audited as `transfer.medallion_verified`. Alternatively, the examiner may flag the request deficient, moving it `UNDER_REVIEW` → `DEFICIENT` and recording a `deficiency_reason` along with the same `last_examiner_id` update. A deficiency is curable: the transferor or an examiner cures it, returning the request `DEFICIENT` → `UNDER_REVIEW` with the `deficiency_reason` cleared, and the flag-and-cure cycle may repeat as often as the paperwork requires.

Approval belongs to a `TransferSupervisor`, and only over a medallion-verified request: the approval moves `MEDALLION_VERIFIED` → `APPROVED` and records the supervisor's identifier in `approved_by`. Segregation of duties is hard-enforced here — the approving supervisor's `X-User-ID` must differ from the request's `last_examiner_id`, so the operator who verified the medallion or flagged the deficiency can never approve the same item; a violation is refused with `ERR_SEGREGATION_OF_DUTIES`. A supervisor may instead reject the request from any of `UNDER_REVIEW`, `MEDALLION_VERIFIED`, or `DEFICIENT`, moving it to the terminal `REJECTED` state, and the transferor may cancel it from `UNDER_REVIEW` or `DEFICIENT`, moving it to the terminal `CANCELLED` state. Both rejection and cancellation decrement the from-account's `pending_transfer_count` by one and advance the account's `version` by one.

Settlement is the final, cascade-heavy step, performed by a `TransferSupervisor` over an `APPROVED` request. Five gates must all pass at settle time. The issuer must be `ACTIVE` — settlement in a `SUSPENDED` security is refused as `ERR_INVALID_STATE`. If the request names a `source_certificate_id`, that certificate must still be `ISSUED`; if a stop-transfer order has since been placed on it, settlement is refused with `ERR_CERTIFICATE_STOPPED`. The logical clock must not fall inside any of the issuer's freeze windows: any window in `SCHEDULED` or `ACTIVE` status whose `start_date` and `end_date` bracket the current instant — both boundary days included — blocks settlement with `ERR_TRANSFER_FREEZE_CONFLICT`. And the source shares must still be available: for a book-entry transfer the source position's `book_entry_shares` must still cover the `share_quantity`, and for a certificated transfer the certificate's face quantity must still equal it; a request whose availability has changed since approval is refused with `ERR_INVALID_STATE`.

A successful settlement moves the request `APPROVED` → `SETTLED` and executes three cascades in order. First, a certificated source certificate moves `ISSUED` → `CANCELLED`. Second, the source position is debited — its `certificated_shares` for a certificated source, its `book_entry_shares` for a DRS source — and the transferee's position in the same issuer is credited in book-entry form, the position being created on the spot when the transferee does not already hold one, with the credited amount landing in its `book_entry_shares`. Third, the issuer's `total_book_entry_shares` and `total_certificated_shares` are recomputed across all positions. Finally the from-account's `pending_transfer_count` is decremented by one and its `version` advanced, the request's `settled_at` is stamped from the logical clock, and the settlement is audited as `transfer.settle`. Transfer requests can be listed with optional `from_account_id`, `to_account_id`, `issuer_id`, `source_certificate_id`, and `status` filters, read singly, per account, or per issuer.

### 3.4. Lost Certificates and Indemnity Bonds

When a physical certificate goes missing, the holder — or a `TransferExaminer` on the holder's behalf — reports it lost, supplying the claimed `loss_date`. The certificate must be `ISSUED`, and it must not already have an open claim: a certificate with a claim still in `FILED`, `BOND_POSTED`, or `APPROVED` status refuses a second report with `ERR_DUPLICATE_OPEN_CLAIM`, because the earlier stop-transfer occupancy is still in force. Reporting places the stop-transfer order: the certificate moves `ISSUED` → `LOST_REPORTED`, its `lost_reported_at` is stamped from the logical clock, and the stop remains open-ended until resolved. In the same operation a `LostCertificateClaim` is created in `FILED` status: its `certificate_id` names the lost certificate, its `claimant_account_id` is copied from the certificate's owning account, its `loss_report_price_cents` is frozen at the issuer's `current_market_price_cents` at the moment of the report, its `replacement_certificate_id` is null and stays null until a replacement is actually issued, and its `filed_by_examiner_id` records the examiner's identifier when an examiner filed the report, remaining null when the holder filed it themselves. The report is audited as `certificate.report_lost`, and the newly created claim is the resource returned to the caller.

If the original certificate turns up, an examiner recovers it. Recovery moves the certificate `LOST_REPORTED` → `ISSUED` and clears its `lost_reported_at`, ending the stop-transfer occupancy. Any claim still open against the certificate — one in `FILED` or `BOND_POSTED` status — moves to `WITHDRAWN` in the same operation, and its bond obligation is voided. The recovery is audited as `certificate.recover`.

Replacement, when the certificate stays lost, runs through the claim's bond-and-approval pipeline. An examiner posts the indemnity bond by submitting the `bond_variant` and the tendered `premium_paid_cents`; the claim must be `FILED`. The bond basis depends on the variant. Under `OPEN_PENALTY`, the reference price is the issuer's `current_market_price_cents` read at the moment the bond is posted, so a bond posted after a market move prices against the newer market. Under `FIXED_PENALTY`, the reference price is the claim's `loss_report_price_cents`, frozen when the loss was first reported, so the bond is priced as of the loss report regardless of later market movement. In both variants the `bond_amount_cents` is the certificate's `share_quantity` multiplied by the variant's reference price, multiplied by two — the standard double-indemnity basis. The `required_premium_cents` is then tiered: 3 percent of the portion of the bond amount up to a cap of ten million cents (one hundred thousand dollars), plus 2 percent of any portion of the bond amount above that cap, with the total rounded half-up to a whole cent. Both computed figures are frozen onto the claim at this point, and the tendered premium must be at least the computed `required_premium_cents`; a tender even one cent short is refused with `ERR_BOND_PREMIUM_INSUFFICIENT`. A successful posting moves the claim `FILED` → `BOND_POSTED`.

Approval of a bonded claim belongs to a `TransferSupervisor` and moves `BOND_POSTED` → `APPROVED`, audited as `claim.approve`. Segregation of duties applies as on the transfer desk, with one asymmetry: when the claim was filed by an examiner, the approving supervisor's `X-User-ID` must differ from the claim's `filed_by_examiner_id`, and a violation is refused with `ERR_SEGREGATION_OF_DUTIES`; when the holder filed the claim themselves and `filed_by_examiner_id` is null, no segregation constraint applies. A supervisor may instead reject a bonded claim, moving it `BOND_POSTED` → `REJECTED`; the underlying certificate then remains `LOST_REPORTED`, its stop-transfer order staying in force.

Issuing the replacement is the terminal act. Over an `APPROVED` claim, the supervisor's issuance moves the claim `APPROVED` → `REPLACED`, moves the original certificate `LOST_REPORTED` → `REPLACED`, and mints a new certificate in `ISSUED` status for the same `share_quantity` as the original, recording its identifier on the claim as `replacement_certificate_id`. The position's `certificated_shares` is deliberately unchanged by the exchange — a replacement preserves the certificate form of the holding — and the issuance is audited as `claim.replaced`. Claims can be listed with optional `certificate_id`, `claimant_account_id`, `replacement_certificate_id`, and `status` filters, and read singly.

### 3.5. Dividends: Declaration, Accrual, Disbursement, and Stale-Dating

An `IssuerOfficer` declares a cash dividend by submitting the `issuer_id`, the `record_date` that fixes the holder-of-record cutoff, the `payable_date` on which money moves, and the `amount_per_share_millicents` — the per-share dividend in thousandths of a cent, so that a declaration of 667 millicents pays two-thirds of a cent per share. The `payable_date` must fall strictly after the `record_date`; a payable date on the record date itself, or before it, is refused with `ERR_INVALID_DATE_RANGE`. Declaring over a `SUSPENDED` issuer is refused with `ERR_ISSUER_SUSPENDED`. A new declaration enters in `DECLARED` status, and the creation is audited as `declaration.create`. Before the record date arrives, the officer may still void the declaration, moving it `DECLARED` → `VOIDED`; no payments are ever generated for a voided declaration, and clock evaluation skips `VOIDED` declarations entirely.

Accrual is clock-driven. When the logical clock reaches a `DECLARED` declaration's `record_date`, the declaration moves `DECLARED` → `ACCRUED` — provided the issuer is `ACTIVE` at evaluation time, since the `ERR_ISSUER_SUSPENDED` gate applies to clock-driven accrual just as it does to transfer creation and declaration creation. At that instant the server walks every `ACTIVE` position of the declaring issuer whose owning account is not `ESCHEATED` and generates one `DividendPayment` per eligible position, in `ACCRUED` status. Each payment's `eligible_shares` is a snapshot of the position's `total_shares` — its `book_entry_shares` plus its `certificated_shares` — taken at the record-lock instant. Transfers settled after the record instant never reduce the snapshot; transfers settled at or before it are already reflected in the positions. When several transfers settle within the same sweep, they apply in `settled_at` ascending order with ties broken by `created_at` ascending — never by identifier — so the snapshot is deterministic.

The gross amount of each payment obeys a pinned rounding order. Per payment, the `eligible_shares` are multiplied by the `amount_per_share_millicents`, yielding a gross figure in millicents; that figure is divided by one thousand and rounded half-up to a whole cent, giving the payment's `gross_cents`. Only then does the declaration aggregate: its `total_accrued_cents` is the sum of the already-rounded per-payment `gross_cents`, and its `total_eligible_shares` is the sum of the `eligible_shares` over the generated payments. Aggregating millicents first and rounding once at the end is forbidden, because it yields different cents. Consider two accounts each holding a single share against a declaration of 667 millicents per share: each payment's gross rounds to one cent, and the declaration total is two cents — summing first would round thirteen hundred thirty-four millicents to a single cent. Both totals are frozen at accrual, and `total_accrued_cents` is immutable from `ACCRUED` onward: an invariant anchor against which all later disbursement activity reconciles.

Each generated payment also carries a provisional withholding, computed against the account's tax attributes as they stand on the record date and stored in `provisional_withholding_cents`. The withholding rate is determined combinatorially from the account's `tin_status`, `residency`, and `treaty_tier`. When the `tin_status` is `MISSING` or `UNCERTIFIED`, the backup withholding rate of 24 percent applies. When the `tin_status` is `CERTIFIED` and the `residency` is `US`, the rate is zero. When the `tin_status` is `CERTIFIED` and the `residency` is `FOREIGN`, the treaty tier decides: a `TREATY` tier withholds 15 percent, and a `STANDARD` tier withholds 30 percent. The withheld amount is the `gross_cents` multiplied by the applicable rate, rounded half-up to a whole cent.

Disbursement is likewise clock-driven. When the logical clock reaches an `ACCRUED` declaration's `payable_date`, the declaration moves `ACCRUED` → `PAYABLE`, and every one of its payments moves `ACCRUED` → `DISBURSED` in the same evaluation. At this point each payment's withholding is recomputed under the identical rate rules, but now against the account's tax attributes as of the payable date; the result is stored as the final `withholding_cents`, and the payment's `net_cents` is its `gross_cents` minus its `withholding_cents`. Because a holder's W-9 certification may change between the record and payable dates, the final `withholding_cents` can legitimately diverge from the earlier `provisional_withholding_cents` on identical share counts. Each disbursed payment's `disbursed_at` is stamped from the logical clock — the anchor of the stale-dating clock described below.

Once disbursed, a payment lives in the holder's hands. The payee — a `Shareholder` whose `X-User-ID` equals the payment's `account_id` — cashes it, moving it `DISBURSED` → `RECONCILED`, the payment's terminal good state. Cashing is a qualifying owner contact: it refreshes the account's `last_qualifying_contact_date` to the logical clock, and when the account was `DORMANT` it brings the account back `DORMANT` → `ACTIVE` with the case-reactivation cascade of §3.7.

The mail, however, sometimes fails. A `ServiceAgent` marking a disbursed payment undeliverable moves it `DISBURSED` → `RETURNED`, stamps its `returned_at` from the logical clock, and flips the account's `address_verified` to false — the register now distrusts the mailing address. Reissue is the cure, also a `ServiceAgent` operation: a `RETURNED` payment may be reissued only after the address has been verified again, so an account whose `address_verified` is still false refuses the reissue with `ERR_ADDRESS_UNVERIFIED`. A successful reissue returns the payment `RETURNED` → `DISBURSED` and restamps `disbursed_at` from the logical clock, restarting the stale-dating clock from zero; the payment may later be returned again, and the return-and-reissue cycle may repeat.

A payment nobody cashes eventually goes stale. When the logical clock reaches the instant one hundred eighty days after a payment's `disbursed_at` — the boundary day itself counts — a `DISBURSED` payment moves `DISBURSED` → `STALE_DATED`. The account's `stale_dividend_cents` is then increased by the payment's `gross_cents`, keeping a running total of unclaimed cash on the account. And when the account is already `DORMANT` and has no escheatment case open in `IDENTIFIED`, `NOTICE_SENT`, or `REPORTED` status, the stale-dating creates a fresh `IDENTIFIED` case — or re-arms a `REACTIVATED` one — so the unclaimed cash pulls the account into the escheatment pipeline of §3.7.

A declaration closes by bubble-up: once every one of its payments has reached a terminal state — `RECONCILED` or `ESCHEATED` — the declaration moves `PAYABLE` → `CLOSED` automatically, and the closure is audited as `declaration.closed`. Declarations can be listed with optional `issuer_id` and `status` filters, read singly with their frozen totals, and payments can be listed with optional `declaration_id`, `account_id`, and `status` filters or read singly. For issuer reporting, an `IssuerOfficer` or `AgentAdmin` can pull the record-date list for a declaration — the holder-of-record snapshot — which returns the `declaration_id`, the `record_date`, the `total_shares` and `total_accounts` of the eligible register, and the per-holder `entries` rows.

### 3.6. Restricted Stock and Legend Removal

Shares carrying a restrictive legend cannot trade freely until the legend is removed, and the workflow begins when a `Shareholder` files a legend-removal request. The payload names the `position_id` of the restricted position, the `account_id` of the holder, the `share_quantity` to release, the `rule_basis` for the exemption — the platform recognizes exactly one basis, `RULE_144` — the `acquisition_date` on which the restricted shares were acquired, and the optimistic-concurrency token `expected_position_version` of §2.7. The `account_id` must be the account that owns the referenced position; a mismatch is refused with `ERR_POSITION_ACCOUNT_MISMATCH`. A `share_quantity` below one is refused with `ERR_ZERO_SHARE_QUANTITY`, and one exceeding the position's `restricted_shares` is refused with `ERR_INSUFFICIENT_RESTRICTED_SHARES`. A valid request enters `SUBMITTED` status, increments the position's `pending_legend_removal_count` by one, advances the position's `version` by one — the movement the next requester's `expected_position_version` must observe — and is audited as `legend.create`.

The request then needs a legal opinion. Submitting issuer counsel's opinion letter — a payload carrying the `counsel_opinion_reference`, filed by the holder or by a `ComplianceOfficer` — moves the request from `SUBMITTED` to `OPINION_UNDER_REVIEW`. A `ComplianceOfficer` reviewing the package may flag it deficient, moving it `OPINION_UNDER_REVIEW` → `DEFICIENT` and recording the `deficiency_reason`. Deficiency is curable here as on the transfer desk: resubmitting the opinion from `DEFICIENT` returns the request to `OPINION_UNDER_REVIEW` with the `deficiency_reason` cleared, and the flag-and-resubmit cycle may repeat as often as counsel requires.

Approval is a `ComplianceOfficer` act over a request in `OPINION_UNDER_REVIEW`, and it enforces the Rule 144 holding period: the logical clock must have reached the instant one hundred eighty days after the request's `acquisition_date`. The boundary is inclusive — a request exactly one hundred eighty days old is eligible — while an approval even one second short is refused with `ERR_HOLDING_PERIOD_NOT_MET`. Approval moves the request `OPINION_UNDER_REVIEW` → `LEGEND_REMOVED`, reduces the position's `restricted_shares` by the request's `share_quantity`, decrements the position's `pending_legend_removal_count` by one, advances the position's `version` by one, and is audited as `legend.removed`. A `ComplianceOfficer` may instead reject the request from `SUBMITTED`, `OPINION_UNDER_REVIEW`, or `DEFICIENT`, moving it to the terminal `REJECTED` state; rejection decrements the `pending_legend_removal_count` and advances the position's `version` just as approval does. Requests can be listed with optional `position_id`, `account_id`, and `status` filters, and read singly.

### 3.7. Dormancy, Escheatment, and Reactivation

Property is presumed abandoned when its owner goes silent for the statutory dormancy period, and the platform determines that period from the account's `state_code` via its computed `dormancy_years`: three years for `CA`, five years for `NY`, three years for `TX`, and five years for every other state. An `ACTIVE` account becomes dormant when the logical clock has reached the instant exactly that many years after its `last_qualifying_contact_date`. The boundary is inclusive — an account whose last qualifying contact was exactly `dormancy_years` ago, to the very second, is dormant — while an account one second short of the anniversary is not.

The dormancy sweep is an `AgentAdmin`-invoked scan over the register. It considers only `ACTIVE` accounts — a `RESTRICTED` account is never swept — and moves each account that has crossed its dormancy horizon `ACTIVE` → `DORMANT`, audited as `account.dormant`. For each newly dormant account that still holds property — any position with `total_shares` above zero, or a nonzero `stale_dividend_cents` balance — and that has no escheatment case currently open in `IDENTIFIED`, `NOTICE_SENT`, or `REPORTED` status, the sweep opens an `EscheatmentCase` in `IDENTIFIED` status, recording the account's `last_qualifying_contact_date` at identification as the case's `dormancy_start_date`. When the account's previous case ended in `REACTIVATED`, that same case is re-armed `REACTIVATED` → `IDENTIFIED` with a refreshed `dormancy_start_date`, so property may dormancy-cycle repeatedly until it is finally remitted. The sweep reports back the `accounts_marked_dormant` and `cases_created` counts, and the run is audited as `escheatment.scan`.

The case then walks a regulated pipeline. A `ComplianceOfficer` sends the due-diligence notice, moving the case `IDENTIFIED` → `NOTICE_SENT` and stamping `notice_sent_at` from the logical clock. Reporting to the state comes next, but only after the notice window has run: the logical clock must have reached the instant sixty days after `notice_sent_at`, the boundary day itself being eligible, and an earlier report is refused with `ERR_NOTICE_WINDOW_NOT_ELAPSED`. Reporting moves the case `NOTICE_SENT` → `REPORTED` and freezes the case's valuation in a pinned order. First the issuer's `current_market_price_cents` at that instant is frozen onto the case as `report_price_cents`. Second, the share leg `share_value_cents` is computed as the sum of `total_shares` across all of the account's positions, multiplied by the frozen `report_price_cents`. Third, the cash leg `cash_value_cents` is computed as the sum of `gross_cents` over all of the account's payments in `STALE_DATED` status. Finally `total_remit_cents` is the sum of the two legs. The order is pinned because the cash leg itself derives from dividends computed on the very shares being valued; all four figures are integer cents with no rounding, since integer share counts multiply integer prices.

Remittance is the terminal cascade, performed by a `ComplianceOfficer` over a `REPORTED` case. It executes in hops. The case itself moves `REPORTED` → `REMITTED`. The account then moves `DORMANT` → `ESCHEATED` — a terminal state, audited as `account.escheated` — and every one of its `ACTIVE` positions moves `ACTIVE` → `CLOSED` with `book_entry_shares`, `restricted_shares`, and `certificated_shares` all zeroed, while every one of its `STALE_DATED` payments moves to `ESCHEATED`, each such payment relieving the account's `stale_dividend_cents` by its own `gross_cents`. Finally the issuer's `total_book_entry_shares` and `total_certificated_shares` are recomputed across all positions. An `ESCHEATED` account is dead to the register: any later mutation targeting it is refused with `ERR_ACCOUNT_ESCHEATED`.

Owners can come back at any point before remittance. A qualifying contact — the holder patching their own account, opening an inquiry, cashing a dividend, or a `ServiceAgent` explicitly reactivating the case — moves a `DORMANT` account back `DORMANT` → `ACTIVE`, refreshes its `last_qualifying_contact_date` to the logical clock, and moves any of the account's cases sitting in `IDENTIFIED` or `NOTICE_SENT` to `REACTIVATED`; the reactivation is audited as `account.reactivate`. A case in `REPORTED` status is past the point of reactivation by contact. A `REACTIVATED` case is not closed — it waits, and a later sweep that finds the account dormant again, still holding positions with `total_shares` above zero or a nonzero `stale_dividend_cents`, re-arms it `REACTIVATED` → `IDENTIFIED` with a refreshed `dormancy_start_date`. Cases can be listed with optional `account_id` and `status` filters, and read singly.

### 3.8. Shareholder Service: Inquiries and Statements

Holders reach the transfer agent through inquiries. A `Shareholder` opens one by supplying the `account_id`, the contact `channel` — one of `PHONE`, `MAIL`, or `EMAIL` — and a free-text `subject`; the inquiry enters in `OPEN` status. Opening an inquiry is itself a qualifying owner contact: it refreshes the account's `last_qualifying_contact_date` to the logical clock, and when the account was `DORMANT` it brings the account back `DORMANT` → `ACTIVE` with the case-reactivation cascade of §3.7.

The service desk works inquiries through a claim discipline. A `ServiceAgent` claiming an inquiry moves it `OPEN` → `IN_REVIEW` and records their identifier in `claimed_by_agent_id`. Only the claiming agent may answer: the answer call requires `X-User-ID` to equal the inquiry's `claimed_by_agent_id`, and a different agent's attempt is refused with `ERR_INQUIRY_CLAIMED_BY_OTHER`. A successful answer records the `answer_text` and moves the inquiry `IN_REVIEW` → `ANSWERED`. An `ANSWERED` inquiry can be claimed again — the follow-up reopen cycle returns it `ANSWERED` → `IN_REVIEW` under the new claimer — and an `ANSWERED` inquiry is closed, by a `ServiceAgent` or by the holder, moving it to the terminal `CLOSED` state, audited as `inquiry.close`. Inquiries can be listed with optional `account_id` and `status` filters, and read singly.

For self-service visibility, a `Shareholder` — or an `AgentAdmin` or `ServiceAgent` assisting them — can read the account's statement, which reports the account's positions and aggregate totals as of the current logical clock. The statement response carries the `account_id`, an `as_of` timestamp taken from the logical clock, the `positions` array, and a `totals` object.

## 4. Endpoint Definitions

All paths below are served from the API root. Operations that create a new resource — onboarding an issuer, registering an account, seeding a position, declaring a freeze window or a dividend, withdrawing a certificate, reporting a certificate lost (which creates the claim), submitting a transfer or legend-removal request, or opening an inquiry — return `201 Created`. All other operations, including reads, patches, and every state-transition action, return `200 OK`. Request payloads, preconditions, and side effects for each operation are defined by the workflows of §3; this table is the address map only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/issuers` | Onboard an issuer security | AgentAdmin |
| GET | `/issuers/{id}` | Read an issuer including computed book-entry and certificated totals | All roles |
| PATCH | `/issuers/{id}` | Update market price and/or status (`ACTIVE` ↔ `SUSPENDED`) | IssuerOfficer |
| POST | `/issuers/{id}/freeze-windows` | Declare a transfer freeze window `[start_date, end_date]` closed interval | IssuerOfficer |
| GET | `/freeze-windows` | List freeze windows; filterable by `issuer_id` and `status` | AgentAdmin, IssuerOfficer, TransferExaminer, TransferSupervisor, ComplianceOfficer |
| GET | `/issuers/{id}/record-date-report` | Issuer record-date list: holder-of-record snapshot for a `declaration_id` | IssuerOfficer, AgentAdmin |
| POST | `/accounts` | Register a shareholder account (registered holder record) | AgentAdmin |
| GET | `/accounts/{id}` | Read an account | All roles |
| PATCH | `/accounts/{id}` | Address / W-9 maintenance; qualifying owner contact | Shareholder, AgentAdmin |
| POST | `/accounts/{id}/restrict` | Place legal-hold restriction (`ACTIVE` → `RESTRICTED`) | ComplianceOfficer |
| POST | `/accounts/{id}/release-restriction` | Lift restriction (`RESTRICTED` → `ACTIVE`) | ComplianceOfficer |
| GET | `/accounts/{id}/statement` | Shareholder statement: positions and totals as of the logical clock | Shareholder, AgentAdmin, ServiceAgent |
| POST | `/accounts/{id}/positions` | Seed a registered-holder position (DRS book-entry) for an issuer | AgentAdmin |
| GET | `/positions` | List positions; filterable by `account_id` and `issuer_id` | All roles |
| POST | `/positions/{id}/certificate-withdrawals` | Convert DRS book shares into a physical certificate | TransferExaminer |
| GET | `/certificates` | List certificates; filterable by `account_id`, `issuer_id`, and `status` | AgentAdmin, TransferExaminer, TransferSupervisor, ComplianceOfficer, Shareholder |
| POST | `/certificates/{id}/convert-to-drs` | Deposit a certificate back into book-entry (`ISSUED` → `CANCELLED`) | TransferExaminer |
| POST | `/certificates/{id}/report-lost` | Report a certificate lost; places stop-transfer order and opens a claim (`FILED`) | Shareholder, TransferExaminer |
| POST | `/certificates/{id}/recover` | Original certificate recovered; stop order lifted, open claim withdrawn | TransferExaminer |
| GET | `/lost-certificate-claims` | List claims; filterable by `certificate_id`, `claimant_account_id`, `replacement_certificate_id`, and `status` | TransferExaminer, TransferSupervisor, AgentAdmin, Shareholder |
| GET | `/lost-certificate-claims/{id}` | Read a single lost-certificate claim | AgentAdmin, TransferExaminer, TransferSupervisor, Shareholder |
| POST | `/lost-certificate-claims/{id}/post-bond` | Post indemnity bond; computes and freezes `bond_amount_cents` and `required_premium_cents` per variant | TransferExaminer |
| POST | `/lost-certificate-claims/{id}/approve` | Approve claim (segregated from filing examiner) | TransferSupervisor |
| POST | `/lost-certificate-claims/{id}/reject` | Reject claim; stop order stays in force | TransferSupervisor |
| POST | `/lost-certificate-claims/{id}/issue-replacement` | Issue replacement certificate; original becomes `REPLACED` | TransferSupervisor |
| POST | `/transfer-requests` | Submit a transfer request (OCC-guarded on from-account version) | Shareholder, TransferExaminer |
| GET | `/transfer-requests` | List transfer requests; filterable by `from_account_id`, `to_account_id`, `issuer_id`, `source_certificate_id`, and `status` | Shareholder, TransferExaminer, TransferSupervisor, AgentAdmin |
| GET | `/transfer-requests/{id}` | Read a single transfer request | AgentAdmin, TransferExaminer, TransferSupervisor, Shareholder |
| POST | `/transfer-requests/{id}/submit-medallion` | Submit medallion signature guarantee; verifies coverage against transfer value | TransferExaminer |
| POST | `/transfer-requests/{id}/flag-deficient` | Flag the request deficient (curable) | TransferExaminer |
| POST | `/transfer-requests/{id}/cure-deficiency` | Cure a deficiency and return to review | Shareholder, TransferExaminer |
| POST | `/transfer-requests/{id}/approve` | Approve a medallion-verified transfer (approver differs from last examiner) | TransferSupervisor |
| POST | `/transfer-requests/{id}/reject` | Reject a non-terminal transfer | TransferSupervisor |
| POST | `/transfer-requests/{id}/cancel` | Transferor cancels a non-approved transfer | Shareholder |
| POST | `/transfer-requests/{id}/settle` | Settle an approved transfer; cascades certificate cancel, position debit/credit, issuer totals | TransferSupervisor |
| POST | `/dividend-declarations` | Declare a cash dividend (record/payable dates, millicents per share) | IssuerOfficer |
| GET | `/dividend-declarations` | List dividend declarations; filterable by `issuer_id` and `status` | AgentAdmin, IssuerOfficer, TransferSupervisor, ServiceAgent, Shareholder |
| GET | `/dividend-declarations/{id}` | Read a declaration including frozen totals | IssuerOfficer, AgentAdmin, TransferSupervisor, ServiceAgent, Shareholder |
| POST | `/dividend-declarations/{id}/void` | Void a declaration before record lock | IssuerOfficer |
| GET | `/dividend-payments` | List dividend payments; filterable by `declaration_id`, `account_id`, and `status` | AgentAdmin, IssuerOfficer, ServiceAgent, Shareholder |
| GET | `/dividend-payments/{id}` | Read a single dividend payment | AgentAdmin, IssuerOfficer, ServiceAgent, Shareholder |
| POST | `/dividend-payments/{id}/cash` | Payee cashes the dividend (`DISBURSED` → `RECONCILED`); qualifying owner contact | Shareholder |
| POST | `/dividend-payments/{id}/mark-returned` | Mark disbursement undeliverable (`DISBURSED` → `RETURNED`) | ServiceAgent |
| POST | `/dividend-payments/{id}/reissue` | Reissue a returned payment to a verified address (`RETURNED` → `DISBURSED`) | ServiceAgent |
| POST | `/legend-removal-requests` | Request restricted-stock legend removal (OCC-guarded on position version) | Shareholder |
| GET | `/legend-removal-requests` | List legend-removal requests; filterable by `position_id`, `account_id`, and `status` | AgentAdmin, ComplianceOfficer, Shareholder |
| GET | `/legend-removal-requests/{id}` | Read a single legend-removal request | AgentAdmin, ComplianceOfficer, Shareholder |
| POST | `/legend-removal-requests/{id}/submit-opinion` | Submit counsel opinion (also cures `DEFICIENT`) | Shareholder, ComplianceOfficer |
| POST | `/legend-removal-requests/{id}/flag-deficient` | Flag the opinion package deficient (curable) | ComplianceOfficer |
| POST | `/legend-removal-requests/{id}/approve` | Approve legend removal (holding period enforced); removes restriction from position | ComplianceOfficer |
| POST | `/legend-removal-requests/{id}/reject` | Reject a legend-removal request | ComplianceOfficer |
| POST | `/escheatment/scan` | Dormancy sweep: marks `ACTIVE` accounts `DORMANT` past their state dormancy period; creates or re-arms escheatment cases for dormant accounts holding shares or stale dividends | AgentAdmin |
| GET | `/escheatment-cases` | List escheatment cases; filterable by `account_id` and `status` | ComplianceOfficer, ServiceAgent, AgentAdmin |
| GET | `/escheatment-cases/{id}` | Read a single escheatment case | AgentAdmin, ComplianceOfficer, ServiceAgent |
| POST | `/escheatment-cases/{id}/send-notice` | Send due-diligence notice (`IDENTIFIED` → `NOTICE_SENT`) | ComplianceOfficer |
| POST | `/escheatment-cases/{id}/report` | File state report after the 60-day notice window; freezes valuation | ComplianceOfficer |
| POST | `/escheatment-cases/{id}/remit` | Remit property to the state; cascades account `ESCHEATED`, positions `CLOSED` and zeroed, stale payments `ESCHEATED` | ComplianceOfficer |
| POST | `/escheatment-cases/{id}/reactivate` | Owner contacted; case `REACTIVATED`, account back to `ACTIVE` | ServiceAgent |
| POST | `/inquiries` | Open a shareholder inquiry; qualifying owner contact (reactivates dormancy) | Shareholder |
| GET | `/inquiries` | List inquiries; filterable by `account_id` and `status` | ServiceAgent, AgentAdmin, Shareholder |
| GET | `/inquiries/{id}` | Read a single inquiry | AgentAdmin, ServiceAgent, Shareholder |
| POST | `/inquiries/{id}/claim` | Claim an inquiry (also reopens `ANSWERED` for follow-up) | ServiceAgent |
| POST | `/inquiries/{id}/answer` | Answer a claimed inquiry (only the claiming agent) | ServiceAgent |
| POST | `/inquiries/{id}/close` | Close an answered inquiry | ServiceAgent, Shareholder |
| GET | `/accounts/{id}/positions` | List positions of an account | All roles |
| GET | `/issuers/{id}/positions` | List positions in an issuer | AgentAdmin, IssuerOfficer, TransferExaminer, TransferSupervisor, ComplianceOfficer |
| GET | `/accounts/{id}/certificates` | List certificates of an account | AgentAdmin, TransferExaminer, TransferSupervisor, ComplianceOfficer, Shareholder |
| GET | `/issuers/{id}/certificates` | List certificates of an issuer | AgentAdmin, IssuerOfficer, TransferExaminer, TransferSupervisor, ComplianceOfficer |
| GET | `/accounts/{id}/transfer-requests` | List transfer requests touching an account as transferor or transferee | AgentAdmin, TransferExaminer, TransferSupervisor, Shareholder |
| GET | `/issuers/{id}/transfer-requests` | List transfer requests for an issuer | AgentAdmin, IssuerOfficer, TransferExaminer, TransferSupervisor |
| GET | `/issuers/{id}/freeze-windows` | List freeze windows of an issuer | AgentAdmin, IssuerOfficer, TransferExaminer, TransferSupervisor, ComplianceOfficer |
| GET | `/audit-events` | Query the tamper-evident audit chain; filterable by `entity_type` and `entity_id` | AgentAdmin, ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint); each set evaluates declaration accrual/payable, payment stale-dating, and freeze-window activation/expiry at the new instant | AgentAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and HTTP status of each.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_ISSUER_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_POSITION_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_DECLARATION_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_LEGEND_REQUEST_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_INQUIRY_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_RESTRICTED` | 409 |
| `ERR_ACCOUNT_ESCHEATED` | 409 |
| `ERR_ISSUER_SUSPENDED` | 409 |
| `ERR_CERTIFICATE_STOPPED` | 409 |
| `ERR_DUPLICATE_CUSIP` | 409 |
| `ERR_DUPLICATE_POSITION` | 409 |
| `ERR_DUPLICATE_OPEN_CLAIM` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INQUIRY_CLAIMED_BY_OTHER` | 403 |
| `ERR_TRANSFER_FREEZE_CONFLICT` | 409 |
| `ERR_FREEZE_WINDOW_OVERLAP` | 409 |
| `ERR_HOLDING_PERIOD_NOT_MET` | 422 |
| `ERR_NOTICE_WINDOW_NOT_ELAPSED` | 422 |
| `ERR_POSITION_ACCOUNT_MISMATCH` | 422 |
| `ERR_ADDRESS_UNVERIFIED` | 422 |
| `ERR_ZERO_SHARE_QUANTITY` | 422 |
| `ERR_INSUFFICIENT_SHARES` | 422 |
| `ERR_INSUFFICIENT_RESTRICTED_SHARES` | 422 |
| `ERR_BOND_PREMIUM_INSUFFICIENT` | 422 |
| `ERR_MEDALLION_COVERAGE_INSUFFICIENT` | 422 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_STALE_POSITION_VERSION` | 412 |
