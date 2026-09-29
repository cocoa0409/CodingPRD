# Exchange Replacement Property Sponsorship API — Product Requirements Document

## 1. Introduction

A Delaware statutory trust sponsor sits at the intersection of two clocks that do not forgive. On one side stands the taxpayer running a like-kind exchange, who has forty-five days to identify replacement property and one hundred eighty days to close it, measured from the day the relinquished property sold. On the other side stands a trust whose powers are deliberately crippled by its own governing instrument: it may not call additional capital, may not refinance debt it has already drawn, may not sign a new lease once its offering has closed, and may not spend trust cash on discretionary capital improvements. This API is the system of record for a sponsor operating inside both sets of constraints at once — sourcing the property, forming the trust, preparing and clearing the offering document, qualifying accredited investors, sequencing their closings against their individual exchange deadlines, and then running the asset through a master lease until the sponsor exits by sale or by conversion.

The product exists because the failure modes here are silent and expensive. An investor whose accreditation lapsed three days before closing is not merely a paperwork problem; a subscription that leaves more taxable boot on the table than the investor agreed to tolerate is a tax event the sponsor caused; a reserve draw that quietly takes the trust below its own reserve floor changes what the trustee is permitted to do next. Every one of those judgements is expressed here as an ordered, deterministic rule with a single machine-readable rejection code, so that the sponsor's operations team, the compliance function, the Delaware trustee, the master tenant and the qualified intermediary all reason from the same numbers.

Two design commitments run through the whole specification. First, segregation of duties is structural rather than advisory: the sponsor principal who submits a private placement memorandum cannot be the compliance officer who declares it effective, and the compliance officer who approves an investor's suitability cannot be the sponsor who closes that investor's subscription. Second, time is explicit. The server never reads the wall clock; every deadline, expiry, accrual and holding period is evaluated against a logical clock that only an operator can advance, so that a closing sequence can be replayed and audited instant by instant.

## 2. Global Specifications & System-Wide Principles

This section fixes the contracts that hold everywhere: authentication, the response envelope, pagination, the logical clock, money and rounding, concurrency, the order in which rejections are decided, and the cross-cutting trust-level principles that gate the workflows in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. A request missing either header, carrying an empty value, or naming a role outside the seven the platform recognises is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is recognised but is not among the roles authorised for the target operation is rejected with `ERR_UNAUTHORIZED` (403).

The seven roles are `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `QualifiedIntermediary` and `PlatformAdmin`.

- The `SponsorPrincipal` is the DST sponsor: it sources property, drafts the offering and its memorandum, onboards investors, writes subscriptions and closes them, prepares and issues tax statements, and proposes, abandons and tallies exits.
- The `ComplianceOfficer` reviews the memorandum, returns it for revision, declares the offering effective or withdraws it, verifies and lapses accredited-investor status, performs suitability review and rejects subscriptions.
- The `Trustee` is the Delaware trustee: it forms the trust, opens it for funding, commits, reprices and funds non-recourse debt, drafts, executes and terminates the master lease, funds capital needs from reserve and voids them, posts debt service, declares, pays and voids distributions, and closes the exit.
- The `Investor` is a beneficial owner. It may rescind its own closed subscription and record its own consent on a proposed exit.
- The `MasterTenant` is the sponsor-affiliated operator that runs the property, remits rent to the trust and may record and fund capital needs from its own pocket.
- The `QualifiedIntermediary` holds exchange proceeds and administers each investor's exchange file, its identifications and its two deadlines.
- The `PlatformAdmin` operates the platform clock and may onboard investors. It holds no trust, offering or exchange authority.

Identity semantics differ by role and matter for ownership checks. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor`; ownership checks on any resource that references an `Investor` compare the resource's investor reference to `X-User-ID` — directly for an `ExchangeFile` or a `Subscription`, and through the named subscription for an `ExitConsent`. When `X-User-Role` is `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `MasterTenant`, `QualifiedIntermediary` or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `ppm_submitted_by_user_id` on an `Offering`, as `suitability_reviewed_by_user_id` on an `Investor`, or by comparing it to the `master_tenant_user_id` recorded on a master lease, which is itself an opaque operator identifier rather than an entity `id`) but never compares it to any entity's `id`.

Two further access rules exist beyond the role list. An ownership violation — an `Investor` acting on a subscription, exchange file or consent that is not its own, or a `MasterTenant` acting on a trust for which it does not hold the executed master lease — is rejected with `ERR_FORBIDDEN_NOT_OWNER` (403). A segregation-of-duties violation, where the acting `X-User-ID` has already performed the conflicting half of the same workflow, is rejected with `ERR_SEGREGATION_OF_DUTIES` (403); the two conflicts are declaring effective an offering whose memorandum the same user submitted, and closing a subscription whose investor suitability the same user approved.

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

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1 and may not be larger than 100. `offset` is the number of rows to skip and defaults to 0; it may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (400).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the returned window.

### 2.4. The Logical Clock and Deadline Arithmetic

Nothing in this system reads the host's wall clock. The server maintains a single logical clock, and every deadline, expiry, accrual window and holding period is evaluated against it. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until an operator moves it, every rule in this document evaluates against that instant, and the server never falls back to real time. A `PlatformAdmin` moves the clock by supplying a `to_iso8601` instant, and the response reports the new `current_utc`. Time moves only when that capability is exercised.

Two deadline conventions recur and must not be confused. Both exchange deadlines are computed from the calendar date of the relinquished closing and then snapped to `23:59:59.999Z` on the target date, so the whole of the final day belongs to the window: a filing that lands exactly on `identification_deadline` is accepted, and one millisecond later is refused. Wherever this document says "at or before" the boundary instant is inside the window; wherever it says "strictly before" the boundary instant is outside it. Day counts between two instants are whole-day counts of the difference measured in UTC.

### 2.5. Common Resource Properties

Every resource the API mints carries an `id`, which is a server-minted UUID with no type prefix and is never supplied by the client. Most resources also carry the full audit set:

- **`id`** (string): the UUID primary key.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the row was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the row, including mutations the server performs on its own initiative when a cascade recomputes a derived field.
- **`version`** (integer): an integer that starts at 1 and increments by exactly 1 on every mutation of the row. Recomputation of a derived field — a trust's balances, an offering's committed totals — is a mutation and therefore bumps `version` and refreshes `updated_at`.

Three record types are append-only journal rows rather than mutable resources, and they carry only `id` and `created_at`: `TrustLedgerEntry`, `DistributionAllocation` and `ExitConsent`. For those three, both `updated_at` and `version` are absent from the representation entirely. Every other resource type — properties, trusts, offerings, investors, exchange files, property identifications, subscriptions, loan facilities, master leases, capital needs, distributions, tax statements and exit events — carries all four fields.

### 2.6. Trust Posture: The Derived Gate Over Every Child Operation

Alongside its lifecycle `status`, every trust carries a derived `posture` that gates what may happen beneath it. Posture is never set by a client; it is recomputed after every mutation of the trust, after every ledger entry booked against it, after every status change of its property and whenever an exit proposal is approved. The three values are `FROZEN`, `RESTRICTED` and `OPEN`, and they are evaluated in strict precedence with the first match winning:

1. If the property the trust was formed to hold is in status `CONTRACT_EXPIRED`, or the trust has any exit event in status `APPROVED`, the posture is `FROZEN`.
2. Otherwise, if the trust's `status` is `OPERATING` and its `reserve_balance_cents` is strictly less than its `reserve_floor_cents`, the posture is `RESTRICTED`.
3. Otherwise the posture is `OPEN`.

`FROZEN` blocks every mutating child operation on the trust, with a deliberate set of exemptions: closing an approved exit, declaring or paying a distribution whose `kind` is `LIQUIDATING`, preparing a tax statement, issuing a tax statement, recording an exit consent, and abandoning a proposed exit all remain available. Any other mutating operation whose target resolves to a frozen trust is rejected with `ERR_TRUST_FROZEN` (409). `RESTRICTED` is narrower: it blocks capital-need funding and both the declaration and the payment of a distribution whose `kind` is `OPERATING`, each rejected with `ERR_TRUST_RESTRICTED` (409), while leaving tax statements, consents and the exit workflow available. A distribution whose `kind` is `LIQUIDATING` is exempt from posture gating altogether, because the exit cascade creates it at a moment when the trust is necessarily frozen.

### 2.7. Money, Ratios and Rounding

All money in this system is integer cents. There are no fractional-cent balances and no floating-point money fields. Every product and quotient in every formula is evaluated in exact rational arithmetic and rounded exactly once, at the step where the rule says to round — never earlier, and never by collapsing two rounding steps into one. Where a rule prescribes two rounding steps in sequence, the order is pinned and reordering it changes cents.

Rounding half up means the value is rounded to the nearest integer with ties going away from zero: a non-negative value has one half added and is then truncated downward, and a negative value is rounded so that a tie moves to the more negative integer of larger magnitude. Where a rule says a value is floored, it is truncated downward to the next lower integer and ties are irrelevant. Where a rule says a division is rounded up, the quotient is raised to the next integer whenever the division is not exact.

Ratios reported as numbers — `occupancy_rate`, `reserve_target_pct`, `load_pct`, `reserve_funding_pct`, `consent_threshold_pct`, `ltv_pct`, `dscr`, `consent_pct` and the unrounded `raw_share_cents` on an allocation row — carry exactly four decimal places and are rounded half up to that precision.

A recurring and deliberate asymmetry: **a reported ratio and the threshold test built on the same inputs are different computations.** Reported ratios round; enforced tests never round. Every threshold in this document is enforced as an exact integer cross-multiplication, which is why a loan whose principal sits one cent above the leverage ceiling fails the test even though its reported `ltv_pct` still displays the ceiling value.

### 2.8. Optimistic Concurrency on Capacity-Bearing Parents

Two write operations consume capacity that belongs to a parent record, and both require the client to prove it is working from a current view of that parent.

Creating a subscription must carry `expected_offering_version`, holding the client's last observed `version` of the target offering. If that value does not equal the offering's current `version`, the create is rejected with `ERR_STALE_OFFERING_VERSION` (412). The rule exists because a subscription create legitimately supersedes the client's picture of remaining capacity: an earlier create already advanced `units_committed`, `equity_committed_cents` and therefore the offering's `version`, so a writer still carrying the older number is sizing its order against capacity the trust has already spent.

Declaring a distribution must carry `expected_trust_version`, holding the client's last observed `version` of the target trust. If that value does not equal the trust's current `version`, the declaration is rejected with `ERR_STALE_TRUST_VERSION` (412). Any intervening reserve draw, rent posting, debt-service payment or capital-need funding advanced `operating_balance_cents` and therefore the trust's `version`, so a declaration carrying the older number is sized against cash that has already moved.

Both fields are required inputs on their respective operations, not optional hints. No other operation in this API takes a version field, and no other operation performs a version check.

### 2.9. Identifier Resolution

Path identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the 404 that comes back. Payload references are resolved after the path, in the order the operation's input list declares them. The mapping from identifier to rejection code is fixed: `ERR_PROPERTY_NOT_FOUND` for a `property_id`, `ERR_TRUST_NOT_FOUND` for a `trust_id`, `ERR_OFFERING_NOT_FOUND` for an `offering_id`, `ERR_INVESTOR_NOT_FOUND` for an `investor_id`, `ERR_EXCHANGE_FILE_NOT_FOUND` for an `exchange_file_id`, `ERR_IDENTIFICATION_NOT_FOUND` for an `identification_id`, `ERR_SUBSCRIPTION_NOT_FOUND` for a `subscription_id`, `ERR_LOAN_NOT_FOUND` for a `loan_id`, `ERR_MASTER_LEASE_NOT_FOUND` for a `lease_id`, `ERR_LEDGER_ENTRY_NOT_FOUND` for a `ledger_entry_id`, `ERR_CAPITAL_NEED_NOT_FOUND` for a `capital_need_id`, `ERR_DISTRIBUTION_NOT_FOUND` for a `distribution_id`, `ERR_ALLOCATION_NOT_FOUND` for an `allocation_id`, `ERR_TAX_STATEMENT_NOT_FOUND` for a `tax_statement_id`, `ERR_EXIT_EVENT_NOT_FOUND` for an `exit_event_id` and `ERR_EXIT_CONSENT_NOT_FOUND` for an `exit_consent_id`. All sixteen are 404s.

Payload-reference resolution applies to trust formation, offering drafting, exchange-file opening, identification filing, subscription creation, loan commitment, lease drafting, capital-need recording, distribution declaration, tax-statement preparation, exit proposal, consent recording and suitability review; the codes it can raise are the property, trust, offering, investor, exchange-file, subscription and exit-event 404s above.

Cascade-created rows are addressable only through their list endpoints: ledger entries the server booked on its own initiative, allocation rows written during a distribution payment, and successor exchange files seeded by an exit close are all discoverable by filtering the corresponding list.

### 2.10. The Order of Rejection

When a request violates more than one rule, exactly one error comes back: the violation with the lowest priority number in the ladder below. Evaluation stops there, and none of the request's side effects are applied. The ladder is global — it is the same ladder for every operation, and an operation simply skips the rungs that do not apply to it. Reading it top to bottom is the only way to predict which of two competing errors a request will produce.

1. Authentication — headers present and role recognised: `ERR_UNAUTHENTICATED`.
2. Role authorisation for the target operation: `ERR_UNAUTHORIZED`.
3. Ownership, on subscription rescission, consent recording, rent posting and capital-need funding: `ERR_FORBIDDEN_NOT_OWNER`.
4. Segregation of duties, on declaring an offering effective and on closing a subscription: `ERR_SEGREGATION_OF_DUTIES`.
5. Request shape — body parses, required fields present, enum members declared, integers within their constraints, the five fractional rates inside their declared ranges, a distribution period whose start is strictly before its end, a lease term whose start is at or before its end, and pagination within bounds: `ERR_INVALID_REQUEST`.
6. Path identifier existence, left to right: the sixteen 404 codes of §2.9.
7. Payload reference existence, in declared field order: the seven payload 404 codes of §2.9.
8. Offering version match on subscription creation: `ERR_STALE_OFFERING_VERSION`.
9. Trust version match on distribution declaration: `ERR_STALE_TRUST_VERSION`.
10. Trust posture is not `FROZEN`, on every mutating operation whose target resolves to a trust except exit close, declaration and payment of a `LIQUIDATING` distribution, tax-statement preparation, tax-statement issuance, consent recording and exit abandonment: `ERR_TRUST_FROZEN`.
11. Trust posture is not `RESTRICTED`, on capital-need funding and on the declaration and payment of an `OPERATING` distribution: `ERR_TRUST_RESTRICTED`.
12. Trust lifecycle status permits the operation — opening funding requires `FORMING`; subscription creation, subscription closing and loan funding require `FUNDING`; lease execution requires `FORMING` or `FUNDING`; capital-need funding, distribution declaration, exit proposal, consent tallying, rent posting and debt-service payment require `OPERATING`; distribution payment requires `OPERATING` or `WINDING_DOWN`; exit close requires `WINDING_DOWN`: `ERR_TRUST_INVALID_STATE`.
13. The offering named by the request is `EFFECTIVE`, on subscription creation, subscription closing and suitability review: `ERR_OFFERING_NOT_EFFECTIVE`.
14. Offering from-state for the requested transition — memorandum submission requires `DRAFT`; memorandum return and declaring effective require `UNDER_REVIEW`; withdrawal requires `DRAFT` or `UNDER_REVIEW`: `ERR_OFFERING_INVALID_STATE`.
15. The trust's property is `ACQUIRED`, on opening funding and on loan funding: `ERR_PROPERTY_NOT_ACQUIRED`.
16. Property from-state — both acquisition and contract expiry require `UNDER_CONTRACT`: `ERR_PROPERTY_INVALID_STATE`.
17. Loan facility from-state — repricing requires `COMMITTED` or `FUNDED` (a `FUNDED` facility passes this rung and is refused later at rung 34 as a prohibited refinancing, so the two codes never collide, while a `PAID_OFF` facility is refused here); funding requires `COMMITTED`; exit close and debt-service payment require the trust's facility to be `FUNDED`: `ERR_LOAN_INVALID_STATE`.
18. A master lease on the trust is `EXECUTED`, on distribution declaration and rent posting: `ERR_MASTER_LEASE_NOT_EXECUTED`.
19. Master lease from-state — execution requires `DRAFT`, termination requires `EXECUTED`: `ERR_MASTER_LEASE_INVALID_STATE`.
20. Subscription from-state — closing requires `RESERVED`; rejection requires `RESERVED` or `REVISION_REQUIRED`; rescission requires `CLOSED`; and a subscription referenced by a consent, by a tax-statement preparation or by a tax-statement issuance must be `CLOSED`: `ERR_SUBSCRIPTION_INVALID_STATE`.
21. Exchange-file status — subscription creation and subscription closing require `IDENTIFIED`; identification filing requires `OPEN` or `IDENTIFIED`; marking expired requires `OPEN` or `IDENTIFIED`: `ERR_EXCHANGE_FILE_INVALID_STATE`.
22. The identification is `ACTIVE` and its exchange file is `IDENTIFIED`, on revocation: `ERR_IDENTIFICATION_INVALID_STATE`.
23. The distribution is `DECLARED`, on payment and on voiding: `ERR_DISTRIBUTION_INVALID_STATE`.
24. Capital-need from-state — funding requires `IDENTIFIED`, voiding requires `IDENTIFIED` or `FUNDED`: `ERR_CAPITAL_NEED_INVALID_STATE`.
25. Exit-event from-state — tallying and abandoning require `PROPOSED`, closing requires `APPROVED`, and a consent may only be recorded against a `PROPOSED` event: `ERR_EXIT_INVALID_STATE`.
26. The tax statement is `DRAFT`, on issuance: `ERR_TAX_STATEMENT_INVALID_STATE`.
27. The logical clock is at or before the subscription's `rescission_deadline`: `ERR_RESCISSION_WINDOW_CLOSED`.
28. The investor's `accreditation_status` is `VERIFIED`, on subscription creation and closing: `ERR_INVESTOR_NOT_ACCREDITED`.
29. The logical clock is strictly before the investor's `accreditation_expires_at`, on subscription creation and closing: `ERR_ACCREDITATION_EXPIRED`.
30. Accreditation method is acceptable to the offering's exemption, on subscription creation and on accreditation verification: `ERR_ACCREDITATION_METHOD_NOT_PERMITTED`.
31. The investor's `suitability_status` is `APPROVED`, on subscription creation and closing: `ERR_SUITABILITY_NOT_APPROVED`.
32. The acknowledged memorandum revision matches the current one, on declaring an offering effective: `ERR_PPM_VERSION_STALE`.
33. No capital call, on capital-need funding: `ERR_CAPITAL_CALL_PROHIBITED`.
34. No refinancing of drawn debt and no repricing after the offering period, on repricing: `ERR_REFINANCING_PROHIBITED`.
35. Trust-level debt is non-recourse, on loan commitment, repricing and funding: `ERR_RECOURSE_DEBT_PROHIBITED`.
36. Structural capital expenditure is not fundable from reserve, on capital-need funding: `ERR_STRUCTURAL_CAPEX_PROHIBITED`.
37. No new lease after the offering period, on lease drafting: `ERR_NEW_LEASE_PROHIBITED`.
38. The logical clock is at or before the file's `identification_deadline`, on identification filing and revocation: `ERR_IDENTIFICATION_WINDOW_CLOSED`.
39. The logical clock is at or before the file's `exchange_deadline`, on subscription creation and closing: `ERR_EXCHANGE_DEADLINE_PASSED`.
40. The logical clock is at or before the property's `contract_close_deadline`, on acquisition: `ERR_PROPERTY_CONTRACT_EXPIRED`.
41. The logical clock is at or after the distribution's `period_end`, on payment: `ERR_DISTRIBUTION_PERIOD_NOT_ENDED`.
42. The elected identification rule still has room, on identification filing: `ERR_IDENTIFICATION_RULE_VIOLATION`.
43. No active identification already names this file-and-property pair, on identification filing: `ERR_DUPLICATE_IDENTIFICATION`.
44. No period overlap, on distribution declaration: `ERR_DISTRIBUTION_PERIOD_OVERLAP`.
45. No lease-term overlap, on lease drafting: `ERR_LEASE_TERM_OVERLAP`.
46. The trust has no live facility already, on loan commitment: `ERR_MULTIPLE_LOANS_PROHIBITED`.
47. The property is not already held by a live trust, on trust formation: `ERR_PROPERTY_ALREADY_TRUSTED`.
48. No consent already exists for this event-and-subscription pair, on consent recording: `ERR_DUPLICATE_CONSENT`.
49. No statement already exists for this trust, subscription, year and convention, on tax-statement preparation: `ERR_DUPLICATE_TAX_STATEMENT`.
50. At least one consent row exists, on consent tallying: `ERR_NO_CONSENTS_RECORDED`.
51. The suitability review was scoped to this offering, on subscription creation: `ERR_SUITABILITY_OFFERING_MISMATCH`.
52. The exchange file belongs to the subscribing investor, on subscription creation: `ERR_EXCHANGE_FILE_INVESTOR_MISMATCH`.
53. The exchange file has an active identification naming the trust's property, on subscription creation and closing: `ERR_IDENTIFICATION_MISSING_FOR_TRUST`.
54. Units requested meet the offering minimum, on subscription creation: `ERR_BELOW_MINIMUM_INVESTMENT`.
55. The investment fits within the investor's suitability cap, on subscription creation: `ERR_SUITABILITY_CAP_EXCEEDED`.
56. Computed boot is within the file's tolerance, on subscription creation: `ERR_BOOT_EXCEEDS_TOLERANCE`.
57. The offering still has room, on subscription creation: `ERR_OFFERING_OVERSUBSCRIBED`.
58. The leverage ceiling holds, on loan commitment, repricing and funding: `ERR_LTV_LIMIT_EXCEEDED`.
59. The coverage floor holds, on loan commitment, repricing and funding: `ERR_DSCR_BELOW_MINIMUM`.
60. Authorised units can raise the grossed-up equity, on declaring an offering effective: `ERR_OFFERING_CAPACITY_SHORTFALL`.
61. The reserve can cover the draw, on capital-need funding: `ERR_RESERVE_INSUFFICIENT`.
62. The operating bucket can cover the payment, on distribution payment and debt-service payment: `ERR_OPERATING_CASH_INSUFFICIENT`.

Note what the ladder implies at rungs 10 through 12: a posture problem always surfaces before a lifecycle-status problem, so an operation attempted against a frozen trust in the wrong status reports `ERR_TRUST_FROZEN`, never `ERR_TRUST_INVALID_STATE`. Similarly, at rungs 28 through 31 an investor who is both unverified and unreviewed reports `ERR_INVESTOR_NOT_ACCREDITED`, and the suitability code only appears once accreditation is clean.

### 2.11. The Trust Ledger and Compensating Reversals

Trust cash lives in exactly two buckets, `OPERATING` and `RESERVE`, and it moves only by ledger entry. Clients never write ledger entries directly except by remitting rent or paying debt service; every other entry is booked by the server as the side effect of a workflow step. Each entry records the trust it hits, its `entry_type`, its `bucket`, a signed `amount_cents` where a positive number credits the bucket and a negative number debits it, the `occurred_at` instant taken from the logical clock, a human-readable `memo` recording provenance such as a reserve draw for a capital need, and a `source_kind` label naming the workflow that produced it. Reversal entries additionally carry `reversal_of_entry_id`, the identifier of the entry they compensate; on every other entry type that field is null.

The `entry_type` vocabulary is `EQUITY_CONTRIBUTION`, `LOAN_PROCEEDS`, `ACQUISITION_PAYMENT`, `SPONSOR_LOAD`, `RESERVE_FUNDING`, `RESERVE_DRAW`, `RENT_RECEIPT`, `DEBT_SERVICE`, `DISTRIBUTION_PAYMENT`, `SALE_PROCEEDS`, `LOAN_PAYOFF` and `REVERSAL`. The `source_kind` vocabulary is `SUBSCRIPTION_CLOSE`, `LOAN_FUNDING`, `ACQUISITION`, `RENT_POSTING`, `DEBT_SERVICE_POSTING`, `CAPITAL_NEED`, `DISTRIBUTION`, `EXIT` and `REVERSAL`; it is a provenance label only and never a foreign key.

Balances are pure replays of the journal, never independently maintained counters. A trust's `operating_balance_cents` is the sum of the signed amounts of its `OPERATING` entries and its `reserve_balance_cents` is the sum of the signed amounts of its `RESERVE` entries. A reversal always carries exactly the negation of the amount of the entry it names, so a reversed entry and the reversal that names it contribute nothing between them: reversing an entry restores the bucket to the balance it held before that entry was booked, exactly, to the cent. This is the compensating invariant behind both unwind paths in the system — rescinding a closed subscription conserves the trust's unit count and equity, and voiding a reserve-funded capital need conserves reserve cash. A reversal entry whose `reversal_of_entry_id` is null names no target and therefore contributes its own signed amount in full; the reserve sweep performed during an exit close is the only such entry.

Where an aggregate filters on `entry_type` rather than summing a whole bucket — the cash figure behind a distribution payment, and the rent and interest totals behind a tax statement — an entry that has been reversed is skipped entirely, because the compensating reversal carries `entry_type` `REVERSAL` and so would never be picked up by the filter.

Two derived unit figures are likewise replays rather than counters. A trust's `units_issued` is the sum of `units_requested` over the subscriptions on that trust's offering whose status is `CLOSED`, and its `equity_raised_cents` is the sum of `investment_amount_cents` over the same set. `units_issued`, not the authorised `total_units`, is the denominator of every per-unit allocation in this system. For reporting purposes the journal is replayed in `occurred_at` ascending order with `created_at` ascending as the tie-break, though the sums themselves are order-independent integer additions.

### 2.12. Trustee Power Restrictions

The trust agreement deliberately narrows what the Delaware trustee may do, and those prohibitions are enforced as first-class rules rather than left to operational discipline. Five of them bite:

- **No capital calls.** A capital need may never be funded by calling additional capital from the beneficial owners. A funding request naming `CAPITAL_CALL` as its `funding_source` is refused with `ERR_CAPITAL_CALL_PROHIBITED` (422), which is why `CAPITAL_CALL` never appears as a persisted value — the only two values a funded capital need can carry are `RESERVE` and `MASTER_TENANT`.
- **No refinancing.** Debt the trust has already drawn may not be renegotiated, and no facility may be repriced at all once the offering period has ended. A repricing request against a facility already in status `FUNDED`, or against a facility whose trust is in `OPERATING`, `WINDING_DOWN`, `TERMINATED` or `CONVERTED_LLC`, is refused with `ERR_REFINANCING_PROHIBITED` (422).
- **No recourse debt.** Trust-level debt must be non-recourse at commitment, at repricing and at funding. Any of the three carrying a `recourse_type` of `RECOURSE` is refused with `ERR_RECOURSE_DEBT_PROHIBITED` (422). A trust may hold only one live facility at a time: a second facility requested while one is already in `COMMITTED` or `FUNDED` status is refused with `ERR_MULTIPLE_LOANS_PROHIBITED` (409).
- **No discretionary capital improvements.** A capital need whose `need_type` is `STRUCTURAL_CAPEX` may not be funded out of trust reserves; only the master tenant may fund it. A funding request naming `RESERVE` against a structural need is refused with `ERR_STRUCTURAL_CAPEX_PROHIBITED` (422).
- **No new leases.** Once the trust has left the offering period — that is, once its status is `OPERATING`, `WINDING_DOWN`, `TERMINATED` or `CONVERTED_LLC`, at which point it necessarily already holds a master lease in status `EXECUTED` — drafting another lease is refused with `ERR_NEW_LEASE_PROHIBITED` (422). All operating flexibility must run through the lease already in place.

## 3. Business Logic & Workflows

### 3.1. Sourcing the Property and Forming the Trust

Everything begins with a candidate replacement property. A `SponsorPrincipal` registers one by supplying its marketing `name`, the `state_code` where it sits (exactly two uppercase letters), its `asset_type` — one of `INDUSTRIAL`, `MULTIFAMILY`, `RETAIL` or `OFFICE` — the contract `purchase_price_cents` and the third-party `appraised_value_cents` (each at least 1 cent), the underwritten `annual_noi_cents` (zero or more), the `occupancy_rate` at underwriting as a fraction between 0.0000 and 1.0000 inclusive, and the `contract_close_deadline`, which is the outside date on the purchase contract. The property is created in status `UNDER_CONTRACT`. Properties are listable and filterable by `state_code`, `asset_type` and `status`.

Acquisition drives `UNDER_CONTRACT → ACQUIRED` and is available only to the sponsor. It requires the property to still be `UNDER_CONTRACT`, and it requires the logical clock to be at or before the `contract_close_deadline`; a sponsor arriving after that instant is refused with `ERR_PROPERTY_CONTRACT_EXPIRED`. On success the server stamps `acquired_at` with the current logical instant and computes the property's `depreciable_basis_cents`, which is the improvement portion of the price: eighty percent of `purchase_price_cents`, land being excluded as the remaining twenty percent, rounded half up to whole cents. A companion figure, the annual depreciation allowance, is the `depreciable_basis_cents` divided over a thirty-nine-year recovery period, rounded half up to whole cents. That annual figure is deliberately **not** stored on the property; it is recomputed from `depreciable_basis_cents` whenever a tax statement needs it, and the two roundings are applied in the order just given — basis first, then the annual allowance from the rounded basis.

The mirror-image transition, `UNDER_CONTRACT → CONTRACT_EXPIRED`, records that the purchase contract lapsed unexercised. It is likewise sponsor-driven, requires the property to be `UNDER_CONTRACT`, and requires the logical clock to be strictly after the `contract_close_deadline` — a contract cannot be declared lapsed while it is still live. Its cascade reaches upward into every trust that was formed to hold this property and whose status is `FORMING` or `FUNDING`: each such trust has its `posture` recomputed and, because the property is now `CONTRACT_EXPIRED`, each lands on `FROZEN`. A property also reaches `DISPOSED` from `ACQUIRED`, but never by direct request: only the exit-close cascade of §3.9 moves it there, and it does so for both exit modes alike.

A `Trustee` forms the Delaware statutory trust that will hold exactly one such property, naming the `property_id` it will acquire, the legal `trust_name`, the `total_units` of beneficial interest the trust agreement authorises (at least 1), the `reserve_floor_cents` below which the reserve bucket may not comfortably sit (zero or more), and the `reserve_target_pct`, a fraction between 0.0000 and 1.0000 inclusive expressing the target reserve as a share of the property's purchase price. The trust is created in status `FORMING` with `posture` `OPEN`, with `units_issued`, `equity_raised_cents`, `operating_balance_cents` and `reserve_balance_cents` all zero, with `property_acquired_at` still empty and with `springing_llc_armed` false. A property may back only one live trust: if a trust already holds it in status `FORMING`, `FUNDING`, `OPERATING` or `WINDING_DOWN`, formation is refused with `ERR_PROPERTY_ALREADY_TRUSTED`. Trusts are listable and filterable by `property_id`, `status` and `posture`, which is how a reader walks from a property to the trust that holds it.

Opening the trust for investor closings advances it `FORMING → FUNDING` and is the gate that proves the deal is actually assembled. The trustee may only open a trust that is still `FORMING`, whose `posture` is `OPEN`, whose property has reached `ACQUIRED` (otherwise `ERR_PROPERTY_NOT_ACQUIRED`), on which exactly one offering stands in status `EFFECTIVE`, and on which exactly one loan facility stands in status `COMMITTED` or `FUNDED`. On success the trust copies the property's `acquired_at` into its own `property_acquired_at`, which becomes the start of the trust's depreciation holding period, and its `version` advances by one.

### 3.2. The Offering: Memorandum Revisions and the Grossed-Up Capital Stack

An offering is the instrument through which the trust's units are sold, and a `SponsorPrincipal` drafts it against a `trust_id`. The draft fixes the `exemption_rule` the offering relies on — either `RULE_506B` or `RULE_506C` — the `unit_price_cents` for one unit of beneficial interest (at least 1), the `min_units_per_investor` any single subscription must reach (at least 1), the sponsor's `load_pct` as a fraction of gross equity (at least 0.0000 and strictly below 1.0000), the third-party `closing_costs_cents` of the acquisition (zero or more), the `reserve_funding_pct` of the purchase price to be funded into reserve at closing (between 0.0000 and 1.0000 inclusive), and the `rescission_window_days` during which an investor may still unwind a closed subscription (zero or more). The offering is created in status `DRAFT` with `ppm_version` 1 and with `units_committed` and `equity_committed_cents` at zero. Offerings are listable and filterable by `trust_id`, `status` and `exemption_rule`.

The private placement memorandum then travels a review loop. The sponsor submits it with a `ppm_document_reference`, moving the offering `DRAFT → UNDER_REVIEW`; the submission is refused if the trust's posture is `FROZEN`, and it records the submitting sponsor's `X-User-ID` as `ppm_submitted_by_user_id` for the segregation-of-duties test that comes later. A `ComplianceOfficer` may return the memorandum for revision with an optional `review_note`, moving it `UNDER_REVIEW → DRAFT` and incrementing `ppm_version` by exactly 1. This is the cyclic edge of the offering machine: the pair may loop `DRAFT → UNDER_REVIEW → DRAFT` any number of times, and each return raises the revision counter, so a reviewer who read revision 3 and comes back to sign off after two more returns is holding a stale document.

Declaring the offering effective moves it `UNDER_REVIEW → EFFECTIVE` and is reserved to a `ComplianceOfficer`. Three things must hold. The offering must be `UNDER_REVIEW`. The acting officer's `X-User-ID` must differ from the recorded `ppm_submitted_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`. And the request's `acknowledged_ppm_version` must equal the offering's current `ppm_version`, or it is refused with `ERR_PPM_VERSION_STALE`. On success `effective_at` is stamped from the logical clock and the capital stack is pinned.

Pinning the capital stack is the most order-sensitive calculation in the system, because the sponsor's load is a percentage of gross equity while gross equity must itself be large enough to carry that load. The five steps run in exactly this order, drawing on the trust's property purchase price, the offering's own closing costs and reserve percentage, and the committed principal of the trust's single loan facility in status `COMMITTED` or `FUNDED`:

1. `initial_reserve_cents` is the property's `purchase_price_cents` multiplied by `reserve_funding_pct`, rounded half up to whole cents.
2. The net acquisition figure is the `purchase_price_cents` plus the offering's `closing_costs_cents` minus the facility's `principal_cents`.
3. The base need is that net acquisition figure plus `initial_reserve_cents`.
4. The load percentage is converted to whole basis points by multiplying `load_pct` by ten thousand and rounding half up. `target_equity_cents` is then the base need multiplied by ten thousand and divided by ten thousand minus those load basis points, with the division rounded **up** to the next whole cent whenever it is not exact — rounding up here guarantees the raise can never under-fund the need.
5. `sponsor_load_cents` is `target_equity_cents` minus the base need.

The fifth step is the one implementers get wrong: the sponsor load is the residual implied by the gross-up, never `load_pct` multiplied by `target_equity_cents`. Declaring effective also tests whether the trust could ever raise the number just computed: the authorised unit capacity, being the trust's `total_units` multiplied by the offering's `unit_price_cents`, must be at least `target_equity_cents`, and exact equality passes. A shortfall is refused with `ERR_OFFERING_CAPACITY_SHORTFALL`. The same figures are exposed as a computed read that reports the offering's `offering_id`, the `purchase_price_cents`, the `closing_costs_cents`, the facility's principal as `loan_principal_cents`, the `initial_reserve_cents`, the `net_acquisition_cents` of step 2, the `base_need_cents` of step 3, the `target_equity_cents`, the `sponsor_load_cents`, the `unit_capacity_cents` of the authorised-units test, the `equity_committed_cents` raised so far and the `equity_remaining_cents` still to raise, which is `target_equity_cents` minus `equity_committed_cents`.

Two rolling totals live on the offering and are recomputed from its subscriptions rather than incremented blindly: `units_committed` is the sum of `units_requested` over subscriptions in status `RESERVED` or `CLOSED`, and `equity_committed_cents` is the sum of `investment_amount_cents` over the same two statuses. Every event that adds or removes a subscription from that set recomputes both and advances the offering's `version`.

An offering can also leave the happy path. A `ComplianceOfficer` may withdraw one that is still `DRAFT` or `UNDER_REVIEW`, with an optional `reason`, driving it to `WITHDRAWN`; in the same operation every subscription on that offering in status `RESERVED` or `REVISION_REQUIRED` is driven to `REJECTED`. An offering can be pushed backwards from `EFFECTIVE → DRAFT`, but only by the repricing cascade described in §3.3, which also raises `ppm_version` by 1 and recomputes the whole capital stack from the new principal. And an offering closes itself: when the trust it belongs to reaches `OPERATING`, the offering moves `EFFECTIVE → CLOSED`, and every subscription still sitting in `RESERVED` on that now-closed offering is driven to `REJECTED`.

### 3.3. Trust-Level Financing and the Master Lease

Debt at the trust level is committed by the `Trustee`, naming the `trust_id`, the `lender_name`, the committed `principal_cents` (at least 1), the fixed `rate_bps` in basis points (zero or more), the `recourse_type`, which must be `NON_RECOURSE` rather than `RECOURSE`, and the `maturity_on` date of the facility. The facility is created in status `COMMITTED` with `repriced_count` at zero and `funded_at` empty, and two ratios are computed and reported on it immediately.

The first is `ltv_pct`, the reported loan-to-value: the `principal_cents` multiplied by ten thousand, divided by the property's `appraised_value_cents`, rounded half up, and then divided by one hundred so the result reads as a percentage carried to four decimal places. The enforced leverage test is a different computation and never rounds: the `principal_cents` multiplied by ten thousand must be no greater than the property's `appraised_value_cents` multiplied by seven thousand five hundred — a ceiling of seventy-five percent expressed in basis points. A facility one cent over the line fails with `ERR_LTV_LIMIT_EXCEEDED` even though its reported `ltv_pct` still displays 75.0000.

The second is `dscr`, the debt-service coverage ratio. The facility is interest-only, so its annual debt service is the `principal_cents` multiplied by `rate_bps` and divided by ten thousand, rounded half up to whole cents. The reported `dscr` is the property's `annual_noi_cents` multiplied by ten thousand, divided by that annual debt service, rounded half up, and then divided by ten thousand so it reads to four decimal places. The enforced coverage test again uses exact integers: the `annual_noi_cents` multiplied by ten thousand must be at least the annual debt service multiplied by twelve thousand five hundred — a floor of 1.2500 times coverage. Falling short is refused with `ERR_DSCR_BELOW_MINIMUM`. Both tests are re-run at commitment, at repricing and at funding. Facilities are listable and filterable by `trust_id`, `status` and `recourse_type`.

Repricing is a self-loop that leaves the facility in `COMMITTED` while re-cutting its terms, and it is the head of a three-hop cascade. The trustee supplies a new `principal_cents`, a new `rate_bps` and the `recourse_type`, which must still be `NON_RECOURSE`. Repricing is permitted only while the trust is `FORMING` or `FUNDING`; a `PAID_OFF` facility is refused as an invalid facility state, while a facility already `FUNDED`, or any facility whose trust has moved beyond the offering period, is refused as a prohibited refinancing under §2.12. Hop one updates `principal_cents` and `rate_bps`, increments `repriced_count` by 1 and recomputes `ltv_pct` and `dscr`. Hop two follows from hop one: if the trust carries an offering in status `EFFECTIVE` at that moment — the ordinary case once the trust has reached `FUNDING` — that offering is pushed `EFFECTIVE → DRAFT`, its `ppm_version` is incremented by 1, and `initial_reserve_cents`, `target_equity_cents` and `sponsor_load_cents` are recomputed from the new principal, because a changed loan changes how much equity the deal needs. Hop three follows from hop two: every subscription on that offering in status `RESERVED` is moved to `REVISION_REQUIRED`, and each such move removes that subscription's units and dollars from the offering's `units_committed` and `equity_committed_cents`.

Funding the facility advances it `COMMITTED → FUNDED`. It requires the facility to be `COMMITTED`, the trust to be in `FUNDING`, the property to be `ACQUIRED`, the `recourse_type` to be `NON_RECOURSE`, and the leverage test to pass on the current principal. On success `funded_at` is stamped from the logical clock, a `LOAN_PROCEEDS` entry is booked into the `OPERATING` bucket for the full `principal_cents` as a positive amount with `source_kind` `LOAN_FUNDING`, the trust's `operating_balance_cents` is recomputed and the trust's `version` advances. The only other movement a facility ever makes is `FUNDED → PAID_OFF`, which the exit-close cascade performs.

The master lease is how the trust obtains operating flexibility it is not itself permitted to exercise. The `Trustee` drafts it against a `trust_id`, naming the `master_tenant_user_id` — the opaque operator identifier of the `MasterTenant` who will run the property, never an entity identifier — the `term_start_on` and `term_end_on` bounding the term, and the annual `base_rent_annual_cents` and `supplemental_rent_annual_cents` (each zero or more), both accrued on a 365-day basis. The term is a **closed** interval: the first and last days both belong to it, so two leases that merely share a single endpoint day do overlap. Drafting is refused with `ERR_LEASE_TERM_OVERLAP` when the requested term intersects the term of any lease in status `DRAFT` or `EXECUTED` on any trust holding the same property, which is found by walking from each candidate lease's trust to that trust's property. The lease is created in status `DRAFT`, and leases are listable and filterable by `trust_id`, `status` and `master_tenant_user_id`.

Executing the lease advances it `DRAFT → EXECUTED`, stamping `executed_at` from the logical clock. It requires the lease to be `DRAFT`, the trust to be in `FORMING` or `FUNDING`, and the trust's posture not to be `FROZEN`. Execution is a precondition for two later capabilities: rent may only be remitted, and distributions may only be declared, while the trust has a lease in `EXECUTED` status — otherwise both are refused with `ERR_MASTER_LEASE_NOT_EXECUTED`. Termination advances an executed lease `EXECUTED → TERMINATED` with an optional `reason`, and its effect is forward-looking only: rent stops accruing for periods that begin at or after the termination instant, while a lease already terminated still supplies the rent terms for a distribution period it covered.

### 3.4. Investor Qualification: Two Independent Dimensions

An `Investor` record is onboarded by a `SponsorPrincipal` or a `PlatformAdmin` with the investor's `legal_name`, its `entity_type` — one of `INDIVIDUAL`, `JOINT`, `IRA`, `LLC` or `REVOCABLE_TRUST` — the `accreditation_method` it intends to rely on, which is one of `SELF_CERT_INCOME`, `SELF_CERT_NET_WORTH` or `THIRD_PARTY_LETTER`, and the three represented financial figures `annual_income_cents`, `net_worth_cents` and `liquid_net_worth_cents`, each zero or more. The record is created with `accreditation_status` `UNVERIFIED` and `suitability_status` `NOT_REVIEWED`.

Those two statuses are **independent dimensions on the same row**, and this is the single most commonly mis-modelled part of the domain. Accreditation runs `UNVERIFIED → VERIFIED → EXPIRED`. Suitability runs `NOT_REVIEWED → APPROVED` or `NOT_REVIEWED → DECLINED`. Advancing one dimension never touches the other: verifying accreditation leaves `suitability_status` exactly where it was, and a suitability review leaves `accreditation_status` exactly where it was. Investors are listable and filterable by `entity_type`, `accreditation_status`, `suitability_status` and `suitability_offering_id`.

A `ComplianceOfficer` verifies accreditation by supplying an `evidence_reference`, moving the accreditation dimension `UNVERIFIED → VERIFIED`. The server stamps `accreditation_verified_at` with the current logical instant and sets `accreditation_expires_at` to ninety days after it; a verification is good for that ninety-day window and no longer. The same officer records a lapse, moving `VERIFIED → EXPIRED`, but only once the logical clock has reached or passed `accreditation_expires_at` — a live verification cannot be lapsed early — and the lapse leaves both `suitability_status` and `suitability_cap_cents` untouched. Method also matters: a generally solicited offering relying on `RULE_506C` will not accept self-certification, so wherever the operation can see such an offering — at subscription creation through the subscription's own offering, and at accreditation verification through the offering the investor's suitability was scoped to, when one has been recorded — an `accreditation_method` of `SELF_CERT_INCOME` or `SELF_CERT_NET_WORTH` is refused with `ERR_ACCREDITATION_METHOD_NOT_PERMITTED`. A `RULE_506B` offering accepts all three methods.

Suitability review is scoped to one specific offering. The `ComplianceOfficer` supplies a `decision` of `APPROVED` or `DECLINED` together with the `offering_id` under review, and that offering must be in status `EFFECTIVE`. The review records `suitability_offering_id` as the offering reviewed and `suitability_reviewed_by_user_id` as the acting officer's `X-User-ID`, which is the value the closing sponsor will later be compared against. On `DECLINED` the `suitability_cap_cents` is set to zero and no cap arithmetic is performed at all.

On `APPROVED` the `suitability_cap_cents` is the smallest of three caps, each computed by flooring — never by rounding half up — and then compared:

- The **liquidity cap** is the investor's `liquid_net_worth_cents` multiplied by the concentration band its `entity_type` earns, floored. The bands are ten percent for an `IRA`, twenty-five percent for an `INDIVIDUAL` and twenty-five percent for a `JOINT` investor, and thirty-five percent for an `LLC` and thirty-five percent for a `REVOCABLE_TRUST`.
- The **means cap** branches on how accreditation is established. If the `accreditation_method` is `SELF_CERT_INCOME`, it is three times the investor's `annual_income_cents`, floored. For either of the other two methods it is thirty percent of the investor's `net_worth_cents`, floored.
- The **deal cap** is sixty percent of the reviewed offering's `target_equity_cents`, floored, so no single beneficial owner may take more than three fifths of the raise.

The cap that governs is the minimum of those three. It is compared against a subscription's `investment_amount_cents` at creation time, and an over-cap order is refused with `ERR_SUITABILITY_CAP_EXCEEDED`.

### 3.5. Exchange Files, Identifications and the Two Clocks

A `QualifiedIntermediary` opens an exchange file for a taxpayer by naming the `investor_id` running the exchange, its own `qi_reference` string, the `relinquished_closed_on` instant at which the relinquished sale closed, the gross `relinquished_sale_price_cents` (at least 1), the `net_proceeds_cents` it now holds (zero or more), the `debt_retired_cents` discharged on the relinquished property (zero or more), the `identification_rule` elected for the file — either `THREE_PROPERTY` or `TWO_HUNDRED_PCT` — and optionally the `boot_tolerance_cents` the investor will accept, which defaults to zero when omitted. The file is created in status `OPEN` with `source_exit_event_id` empty, that field being populated only on a successor file seeded by an exit close. Exchange files are listable and filterable by `investor_id`, `source_exit_event_id`, `status` and `identification_rule`, and the successor files an exit close creates are discoverable only through that list.

Both clocks start from the calendar date of `relinquished_closed_on`. The `identification_deadline` is forty-five days after that date, snapped to `23:59:59.999Z` on the forty-fifth day; the `exchange_deadline` is one hundred eighty days after that date, snapped to `23:59:59.999Z` on the one-hundred-eightieth day. Both boundaries are inclusive, per §2.4.

Filing an identification names the `exchange_file_id` it is filed under, the `property_id` being identified and the `fair_market_value_cents` attributed to that property (at least 1). The server stamps `identified_at` from the logical clock and assigns a 1-based `sequence_no` within the file, ordinals being assigned in `identified_at` ascending order with `created_at` ascending as the tie-break. The new row is created in status `ACTIVE`, and only `ACTIVE` rows count for anything; a `REVOKED` row is invisible to every capacity test. Filing after the file's `identification_deadline` is refused with `ERR_IDENTIFICATION_WINDOW_CLOSED`, and filing a second `ACTIVE` row for the same exchange-file-and-property pair is refused with `ERR_DUPLICATE_IDENTIFICATION`. Identifications are listable and filterable by `exchange_file_id`, `property_id` and `status`.

The elected identification rule is tested against the set of `ACTIVE` rows on the file plus the row about to be inserted. Under `THREE_PROPERTY` the filing is refused when that candidate set would hold more than three rows — a fourth active identification is one too many. Under `TWO_HUNDRED_PCT` the filing is refused when the candidate set's total `fair_market_value_cents`, multiplied by one hundred, would exceed the file's `relinquished_sale_price_cents` multiplied by two hundred; the test is an exact integer cross-multiplication, so a candidate set landing precisely at twice the relinquished sale price is accepted, and only a set above it is refused. Either refusal carries `ERR_IDENTIFICATION_RULE_VIOLATION`.

The exchange file's own status tracks the identification set. When the first `ACTIVE` identification lands on an `OPEN` file, the file advances `OPEN → IDENTIFIED` and that row takes `sequence_no` 1; the advance requires the logical clock to be at or before the `identification_deadline`. The intermediary may revoke an identification with an optional `reason`, moving it `ACTIVE → REVOKED`; revocation requires the row to be `ACTIVE`, the file to be `IDENTIFIED`, and the logical clock to be at or before the file's `identification_deadline`. Revoking the last `ACTIVE` row on a file walks it back `IDENTIFIED → OPEN`, which is the file's revision loop — identification can be unwound while the forty-five-day window is still open. Crucially, the walk-back changes no deadline: `identification_deadline` is **not** extended by revocation.

Two terminal outcomes remain. `IDENTIFIED → CLOSED_MATCHED` happens when a subscription on the file closes (see §3.6), requires the logical clock to be at or before the `exchange_deadline`, and permanently bars further identifications on that file. `OPEN → EXPIRED` and `IDENTIFIED → EXPIRED` are both driven by the intermediary marking the file expired: from `OPEN` that requires the logical clock to be strictly after the `identification_deadline`, and from `IDENTIFIED` it requires the clock to be strictly after the `exchange_deadline`. Either expiry drives every subscription on that file in status `RESERVED` or `REVISION_REQUIRED` to `REJECTED`.

### 3.6. Subscriptions: Reservation, the Closing Cascade and Rescission

A subscription is created by a `SponsorPrincipal` and names the `offering_id` being subscribed to, the `investor_id` subscribing, the `exchange_file_id` this investment is intended to complete, the `units_requested` (at least 1) and the concurrency token `expected_offering_version`. It is created in status `RESERVED`, and its `investment_amount_cents` is the `units_requested` multiplied by the offering's `unit_price_cents`. Subscriptions are listable and filterable by `offering_id`, `investor_id`, `exchange_file_id` and `status`.

Creation is where the exchange, the investor and the offering are reconciled with one another, and a long list of gates applies. The named offering must be in status `EFFECTIVE`, otherwise `ERR_OFFERING_NOT_EFFECTIVE`. The trust must be in status `FUNDING`, and its posture must not be `FROZEN`. The investor's `accreditation_status` must be `VERIFIED` — an `UNVERIFIED` investor draws `ERR_INVESTOR_NOT_ACCREDITED` — and the logical clock must be **strictly before** the investor's `accreditation_expires_at`, so an investor whose verification expires at exactly this instant draws `ERR_ACCREDITATION_EXPIRED`. Where the offering's `exemption_rule` is `RULE_506C`, the investor's `accreditation_method` must be `THIRD_PARTY_LETTER`. The investor's `suitability_status` must be `APPROVED`, and the investor's `suitability_offering_id` must equal this subscription's `offering_id`, because a suitability review scoped to a different offering says nothing about this one — a mismatch is `ERR_SUITABILITY_OFFERING_MISMATCH`. The exchange file must be in status `IDENTIFIED`, its `investor_id` must equal the subscription's `investor_id` (otherwise `ERR_EXCHANGE_FILE_INVESTOR_MISMATCH`), it must carry an `ACTIVE` identification naming the trust's `property_id` (otherwise `ERR_IDENTIFICATION_MISSING_FOR_TRUST` — a taxpayer may not buy into a property it never identified), and the logical clock must be at or before the file's `exchange_deadline`.

Three fiscal gates then apply in order. The `units_requested` must be at least the offering's `min_units_per_investor`, or `ERR_BELOW_MINIMUM_INVESTMENT`. The `investment_amount_cents` must be no greater than the investor's `suitability_cap_cents`, or `ERR_SUITABILITY_CAP_EXCEEDED`. And the boot test must pass. Boot is the taxable cash the taxpayer fails to reinvest, computed as follows: the investor's `debt_share_cents` is the facility's `principal_cents` multiplied by the `units_requested` and divided by the trust's `total_units`, rounded half up — the only rounded step in the whole computation; the replacement value is the `investment_amount_cents` plus that debt share; the relinquished value is the exchange file's `net_proceeds_cents` plus its `debt_retired_cents`; and `boot_cents` is the relinquished value minus the replacement value, or zero when that difference would be negative, boot never being negative. The subscription is refused with `ERR_BOOT_EXCEEDS_TOLERANCE` when `boot_cents` exceeds the file's `boot_tolerance_cents`; equality is accepted. The same boot figure is recomputed whenever the offering's capital stack is recomputed.

The last gate is capacity. The offering still has room when its `equity_committed_cents` is strictly less than its `target_equity_cents` **and** its `units_committed` plus the new `units_requested` is no more than the trust's `total_units`. This has a deliberate consequence: the straddling subscription — the one whose own dollars carry the raise past `target_equity_cents` — is accepted in full, because the test looks only at what was already committed before it arrived. Only a subscription that arrives when the target is *already* met, or one that would push committed units past the authorised units, is refused with `ERR_OFFERING_OVERSUBSCRIBED`. On success the offering's `units_committed` and `equity_committed_cents` are recomputed and its `version` advances by one.

Closing a subscription is the head of the four-hop cascade and is performed by a `SponsorPrincipal`. It requires the subscription to be `RESERVED`, the offering still `EFFECTIVE`, the trust in `FUNDING` with a posture other than `FROZEN`, the investor still `VERIFIED` with the clock strictly before `accreditation_expires_at`, the investor's `suitability_status` still `APPROVED`, the exchange file still `IDENTIFIED` with the clock at or before its `exchange_deadline`, and the acting sponsor's `X-User-ID` to differ from the investor's `suitability_reviewed_by_user_id` — the officer who blessed the investor may not also be the person who takes the money, and a collision is `ERR_SEGREGATION_OF_DUTIES`.

Hop one is the close itself, moving the subscription `RESERVED → CLOSED`. The subscription's `closed_at` is stamped from the logical clock, its `closing_sequence_no` is assigned, and its `rescission_deadline` is set to `closed_at` plus the offering's `rescission_window_days` days. An `EQUITY_CONTRIBUTION` entry is booked into the `OPERATING` bucket for the full `investment_amount_cents` as a positive amount with `source_kind` `SUBSCRIPTION_CLOSE`. The trust's `units_issued`, `equity_raised_cents` and `operating_balance_cents` are recomputed, and the exchange file moves `IDENTIFIED → CLOSED_MATCHED`. The `closing_sequence_no` is a dense 1-based ordinal within the offering, assigned over the offering's `CLOSED` subscriptions sorted by `closed_at` ascending with `created_at` ascending as the tie-break; `id` is never a sort key.

Hop two fires only when the raise is complete: if the trust's recomputed `equity_raised_cents` is at least the offering's `target_equity_cents`, the trust moves `FUNDING → OPERATING`. That transition additionally requires the trust's facility to be `FUNDED` and a lease on the trust to be `EXECUTED`, and it books the acquisition in four ledger legs, all at once: a `SPONSOR_LOAD` entry in the `OPERATING` bucket for the negative of the offering's `sponsor_load_cents` with `source_kind` `SUBSCRIPTION_CLOSE`; an `ACQUISITION_PAYMENT` entry in the `OPERATING` bucket for the negative of the property's `purchase_price_cents` plus the offering's `closing_costs_cents`, with `source_kind` `ACQUISITION`; and the reserve funding as **two** legs — a `RESERVE_FUNDING` entry in the `OPERATING` bucket for the negative of `initial_reserve_cents` and a `RESERVE_FUNDING` entry in the `RESERVE` bucket for the positive of the same figure, both with `source_kind` `ACQUISITION`. Cash moving between buckets is always two legs, never one. Both balances and then the `posture` are recomputed.

Hop three follows from hop two: because the trust reached `OPERATING`, its `EFFECTIVE` offering moves to `CLOSED`. Hop four follows from hop three: every *other* subscription on that offering still in status `RESERVED` moves to `REJECTED`. A single close by the last investor therefore ends the raise, buys the building, funds the reserve, shuts the offering and turns away everyone still queuing — all inside one request.

A `ComplianceOfficer` may reject a subscription in status `RESERVED` or `REVISION_REQUIRED` with an optional `reason`, driving it to `REJECTED`. Rejecting a `RESERVED` row removes its units and dollars from the offering's committed totals; rejecting a `REVISION_REQUIRED` row has no ledger effect and no committed-total effect, because the repricing cascade already removed it. Subscriptions also reach `REJECTED` without anyone asking, by three system paths: the hop-four sweep just described, an offering withdrawal, and an exchange-file expiry.

Rescission is the investor's own escape hatch and is the system's canonical compensating reversal. The acting `Investor` must be the subscription's own `investor_id`, the subscription must be `CLOSED`, and the logical clock must be at or before the `rescission_deadline`, that boundary instant still being inside the window; arriving later is `ERR_RESCISSION_WINDOW_CLOSED`. The subscription moves `CLOSED → RESCINDED`. The rescission books a `REVERSAL` entry in the `OPERATING` bucket for the negative of `investment_amount_cents`, with `reversal_of_entry_id` pointing at the `EQUITY_CONTRIBUTION` entry booked at close and `source_kind` `REVERSAL`. The trust's `units_issued`, `equity_raised_cents` and `operating_balance_cents` are recomputed, and the governing invariant is that `units_issued` returns to **exactly** its pre-close value — unit count is conserved across a close-and-rescind pair, never merely approximately. The rescinded row's `closing_sequence_no` is cleared to empty and the remaining `CLOSED` subscriptions on the offering are renumbered by the same `closed_at` ascending rule, so the sequence is always 1 through n with no gaps. Finally the exchange file walks back from `CLOSED_MATCHED`: to `OPEN` when the file's `identification_deadline` has not yet passed, and to `EXPIRED` when it has — an investor who unwinds late does not get a fresh identification period, he gets a dead file.

### 3.7. Operating the Property: Rent, Debt Service, Capital Needs and the Reserve

Once the trust is `OPERATING` the money moves through two channels: rent in from the master tenant, and interest out to the lender. Both are recorded as ledger entries at the current logical instant, and both may only be recorded while the trust is `OPERATING` with a posture other than `FROZEN`.

A `MasterTenant` remits rent by supplying the `rent_kind` the payment covers — the label distinguishing base rent from supplemental rent, carried as provenance in the entry's `memo` and having no effect on the arithmetic — and the `amount_cents` remitted. The acting tenant's `X-User-ID` must equal the `master_tenant_user_id` of an `EXECUTED` lease on the target trust, or the request is refused with `ERR_FORBIDDEN_NOT_OWNER`; and some lease on the trust must be `EXECUTED`, or `ERR_MASTER_LEASE_NOT_EXECUTED`. The remittance books a single `RENT_RECEIPT` entry in the `OPERATING` bucket for the positive `amount_cents` with `source_kind` `RENT_POSTING` and `occurred_at` at the current logical instant, recomputes the trust's `operating_balance_cents` and `posture`, and advances the trust's `version` by one. Because `occurred_at` is the logical instant of the request and not the period the rent relates to, a rent payment posted late lands in a later distribution period than the accrual that anticipated it — which is exactly how a reconciliation delta is produced.

A `Trustee` pays scheduled interest by supplying the `amount_cents` paid. The trust's facility must be in status `FUNDED`, and the trust's `operating_balance_cents` must be at least the amount about to leave the bucket, or `ERR_OPERATING_CASH_INSUFFICIENT`. The payment books a single `DEBT_SERVICE` entry in the `OPERATING` bucket for the **negative** of `amount_cents` with `source_kind` `DEBT_SERVICE_POSTING`, recomputes `operating_balance_cents` and `posture`, and advances the trust's `version`.

Capital needs are recorded by either a `Trustee` or a `MasterTenant` against a `trust_id`, naming the `need_type` — `NORMAL_REPAIR`, `TENANT_IMPROVEMENT` or `STRUCTURAL_CAPEX` — the `amount_cents` of the work (at least 1) and the `needed_by` date the work must be funded by. The need is created in status `IDENTIFIED` with `funding_source` and `funded_at` empty. Capital needs are listable and filterable by `trust_id`, `status`, `need_type` and `funding_source`.

Funding a need moves it `IDENTIFIED → FUNDED` and takes a `funding_source` that decides who pays and what the books record. The enum has three declared members and only two are ever persisted: `CAPITAL_CALL` is refused outright with `ERR_CAPITAL_CALL_PROHIBITED`, because the trust may not call capital from its beneficial owners, so no row ever carries it.

With `funding_source` `RESERVE` the actor must be the `Trustee`, the trust must be `OPERATING` with posture exactly `OPEN` — a `RESTRICTED` posture blocks reserve draws with `ERR_TRUST_RESTRICTED`, precisely because the reserve is already below its floor — the `need_type` must not be `STRUCTURAL_CAPEX` (otherwise `ERR_STRUCTURAL_CAPEX_PROHIBITED`, structural work being the master tenant's burden), and the trust's `reserve_balance_cents` must be at least the need's `amount_cents`, or `ERR_RESERVE_INSUFFICIENT`. On success `funding_source` is set to `RESERVE`, `funded_at` is stamped, a `RESERVE_DRAW` entry is booked in the `RESERVE` bucket for the negative of `amount_cents` with `source_kind` `CAPITAL_NEED`, and the trust's `reserve_balance_cents` is recomputed and then its `posture`: a draw that leaves the reserve below `reserve_floor_cents` turns the trust `RESTRICTED` in the same request that drew it.

With `funding_source` `MASTER_TENANT` the actor must be the `MasterTenant`, the trust must be `OPERATING`, and an `EXECUTED` lease on the trust must carry a `master_tenant_user_id` equal to the acting `X-User-ID`. This funding is **outside the trust's books entirely**: no ledger entry is written, `reserve_balance_cents` and `operating_balance_cents` are both unchanged, and the posture cannot move. The need still reaches `FUNDED` with its `funded_at` stamped. Master-tenant funding is therefore also the only route by which a `STRUCTURAL_CAPEX` need can ever be funded.

Voiding a need is available to the `Trustee` from either `IDENTIFIED` or `FUNDED`, with an optional `reason`. Voiding an `IDENTIFIED` need has no ledger effect, the need never having been funded. Voiding a `FUNDED` need whose `funding_source` is `RESERVE` books a compensating `REVERSAL` entry in the `RESERVE` bucket for the **positive** of `amount_cents`, with `reversal_of_entry_id` pointing at the `RESERVE_DRAW` entry and `source_kind` `REVERSAL`; the trust's `reserve_balance_cents` and `posture` are recomputed and reserve cash is conserved exactly, so a trust pushed `RESTRICTED` by the draw returns to `OPEN` on the void. Voiding a `FUNDED` need whose `funding_source` is `MASTER_TENANT` books nothing at all, because nothing was ever booked. Voiding a `FUNDED` need requires the trust to be `OPERATING`.

The trust's own condition is available as a computed read that reports the `trust_id`, its `status` and `posture`, the `units_issued` and the `units_available` still unsold (the `total_units` minus `units_issued`), the `equity_raised_cents`, the `operating_balance_cents` and `reserve_balance_cents`, the `reserve_target_cents` (the property's `purchase_price_cents` multiplied by the trust's `reserve_target_pct`, rounded half up), the `reserve_variance_cents` (the `reserve_balance_cents` minus that target, which is negative when the reserve is short), the `distributions_paid_cents` (the sum of `final_amount_cents` over the trust's distributions in status `PAID`), and the `closed_investor_count` (the count of *distinct* `investor_id` values over the trust's `CLOSED` subscriptions, so one investor holding two closed subscriptions counts once). Note that `reserve_target_cents` and `reserve_floor_cents` are different numbers with different jobs: the target drives reporting and replenishment, the floor drives posture.

### 3.8. Distributions, Allocation Rounding and Grantor-Trust Tax Statements

A `Trustee` declares a distribution naming the `trust_id`, the `kind` — `OPERATING` or `LIQUIDATING` — the `period_start` and `period_end` bounding the period, and the concurrency token `expected_trust_version`. The period is **half-open**: `period_start` is included and `period_end` is excluded, so adjacent periods that share an instant do not overlap. The `period_start` must be strictly before the `period_end`. Declaration requires the trust to be `OPERATING`, a lease on the trust to be `EXECUTED`, and — for `kind` `OPERATING` only — the posture to be neither `FROZEN` nor `RESTRICTED`. The requested interval must not intersect the interval of any distribution on the same trust in status `DECLARED` or `PAID`, or the declaration is refused with `ERR_DISTRIBUTION_PERIOD_OVERLAP`; intervals that merely touch, the earlier `period_end` equalling the later `period_start`, do not intersect. The distribution is created in status `DECLARED` with `declared_at` stamped, `final_amount_cents` and `reconciliation_delta_cents` and `paid_at` all still empty, and the trust's `version` advances. Distributions are listable and filterable by `trust_id`, `status` and `kind`.

Every distribution is measured twice, and the two measurements deliberately disagree. Both share the same shape — a variant-specific gross figure, minus a common reserve replenishment — and both are driven by the `period_days`, the whole number of days from `period_start` to `period_end`.

The reserve replenishment is identical under both variants because it is always an accrual, never a cash figure, and its two roundings run in a pinned order: first annualise, by multiplying the lease's `base_rent_annual_cents` by the trust's `reserve_target_pct` and rounding half up to whole cents; then prorate, by multiplying that annual figure by the `period_days`, dividing by 365 and rounding half up again. Collapsing the two steps into a single product changes the answer by cents and is wrong. The lease supplying the terms is the single lease on the trust in status `EXECUTED` or `TERMINATED` whose term covers the `period_start`.

At declaration, the gross figure is the **`PROVISIONAL_ACCRUAL`** variant and is stored in `provisional_amount_cents`. It ignores entirely whether any cash arrived. Its three components are each rounded half up **independently** before they are combined — round-then-combine, never combine-then-round. The accrued base rent is the lease's `base_rent_annual_cents` multiplied by the `period_days` and divided by 365, rounded half up. The accrued supplemental rent is the lease's `supplemental_rent_annual_cents` treated the same way. The scheduled debt service is a two-step rounding of its own: first the annual interest, being the facility's `principal_cents` multiplied by its `rate_bps` and divided by ten thousand, rounded half up; then that annual figure multiplied by the `period_days`, divided by 365, and rounded half up again. The gross is then the accrued base plus the accrued supplemental minus the scheduled debt service, and `provisional_amount_cents` is that gross minus the reserve replenishment.

At payment, the gross figure is the **`FINAL_CASH`** variant and is stored in `final_amount_cents`. It is never annualised and never accrued: it is the signed sum of the `amount_cents` of the trust's unreversed ledger entries whose `entry_type` is `RENT_RECEIPT` or `DEBT_SERVICE` and whose `occurred_at` lies inside the half-open window from `period_start` up to but excluding `period_end`. Because `DEBT_SERVICE` entries are already negative, that sum is a net cash figure and needs no further sign handling. The `final_amount_cents` is that gross minus the same reserve replenishment, and `reconciliation_delta_cents` is `final_amount_cents` minus `provisional_amount_cents`. A rent receipt that arrives one day late, or a debt-service payment made one day early, therefore produces a non-zero delta for completely unchanged lease and loan terms — which is the whole point of carrying both numbers.

Paying a distribution moves it `DECLARED → PAID` and is performed by the `Trustee`. It requires the distribution to be `DECLARED`, the trust to be `OPERATING` or `WINDING_DOWN`, the logical clock to be at or after the `period_end` — a period may not be paid before it has ended, or `ERR_DISTRIBUTION_PERIOD_NOT_ENDED` — and the trust's `operating_balance_cents` to be at least the amount about to leave the operating bucket, being the `FINAL_CASH` amount plus its reserve replenishment. For `kind` `OPERATING` a `RESTRICTED` posture also blocks payment. On success `paid_at` is stamped, the allocation rows are written, a `DISTRIBUTION_PAYMENT` entry is booked in the `OPERATING` bucket for the negative of `final_amount_cents` with `source_kind` `DISTRIBUTION`, the reserve replenishment is booked as its own two legs — negative in `OPERATING`, equal and positive in `RESERVE` — and the trust's `operating_balance_cents`, `reserve_balance_cents`, `posture` and `version` are all brought up to date.

The split across investors is the second place where rounding order is load-bearing. The pinned order is **round each share first, then sweep the residual**; summing the raw shares and rounding once at the end is explicitly forbidden and produces a different per-investor answer. The amount being split is `final_amount_cents`. The denominator is the trust's `units_issued` — never its `total_units`, so unsold and rescinded units dilute nobody. The rows being split across are the trust's subscriptions in status `CLOSED`, ordered by `closing_sequence_no` ascending and never by `id`; `RESERVED`, `REVISION_REQUIRED`, `REJECTED` and `RESCINDED` subscriptions are excluded entirely. Then, for each row:

1. `raw_share_cents` is the amount multiplied by that row's `units` (the subscription's `units_requested` snapshotted at payment time) and divided by the denominator, kept to four decimal places, rounded half up.
2. `allocated_cents` is `raw_share_cents` rounded half up to whole cents.
3. The residual is the amount minus the sum of every row's `allocated_cents`. It may be positive, negative or zero.
4. When the residual is positive, the rows are ordered by the fractional part of their `raw_share_cents` descending, with `closing_sequence_no` ascending as the tie-break, and one cent is added to each of the first rows, as many rows as the residual has cents. When the residual is negative, the rows are ordered by that fractional part **ascending**, again tie-broken by `closing_sequence_no` ascending, and one cent is subtracted from each of the first rows, as many rows as the residual's magnitude has cents. Each row's `residual_adjustment_cents` records the plus one, minus one or zero that was applied to it.
5. The invariant that must hold afterwards is that the sum of `allocated_cents` across every row equals the amount exactly.

Each allocation row carries its `distribution_id`, its `subscription_id`, its `units`, its `raw_share_cents`, its `allocated_cents` and its `residual_adjustment_cents`. Allocation rows are created only by the payment cascade and are discoverable only through the allocation list, filterable by `distribution_id` and `subscription_id`.

A declared distribution may instead be voided by the `Trustee` with an optional `reason`, moving it `DECLARED → VOIDED`. Voiding writes no ledger entry and releases the period: a `VOIDED` distribution is invisible to the overlap test, so a new distribution may occupy exactly the same half-open interval.

Tax statements are prepared by a `SponsorPrincipal` naming the `trust_id`, the `subscription_id` whose beneficial owner is being reported to, the `tax_year` (2026 or later) and the `allocation_variant` to apply. The referenced subscription must be in status `CLOSED`. A statement is unique per `trust_id`, `subscription_id`, `tax_year` and `allocation_variant` taken together; a second statement for that quadruple is refused with `ERR_DUPLICATE_TAX_STATEMENT`. Deliberately, the *same* subscription and year may carry one statement per convention, so the two conventions can be laid side by side. The statement is created in status `DRAFT` with `issued_at` empty. Tax statements are listable and filterable by `trust_id`, `subscription_id`, `tax_year`, `status` and `allocation_variant`.

Three trust-level totals are computed first, over the window from the first instant of the `tax_year` up to but excluding the first instant of the following year. The trust's rental income is the sum of `amount_cents` over unreversed entries with `entry_type` `RENT_RECEIPT` whose `occurred_at` falls in that window. The trust's interest expense is the sum of `amount_cents` over unreversed entries with `entry_type` `DEBT_SERVICE` in the same window, multiplied by negative one so it is carried as a positive number. The trust's depreciation is another pinned two-step rounding: first annualise, taking the property's `depreciable_basis_cents` divided by thirty-nine and rounded half up; then prorate, multiplying that annual allowance by the held days, dividing by 365 and rounding half up. The held days are the whole days from the date of the trust's `property_acquired_at` through December 31 of the `tax_year`, inclusive of both endpoints, capped at 365 — so a property held for years contributes a full year, and one acquired mid-year contributes only its stub.

Each of the three totals is then multiplied by the investor's exact rational share and rounded half up **independently**, giving `rental_income_cents`, `interest_expense_cents` and `depreciation_cents`. The `net_taxable_income_cents` is then computed from those three *rounded* figures: the `rental_income_cents` minus the `interest_expense_cents` minus the `depreciation_cents`. The share itself depends on the elected convention:

- Under **`UNITS_AT_YEAR_END`** the share is the subscription's `units_requested` divided by the trust's `units_issued`. When the investor closed inside the year is ignored completely: an investor who closed on the last business day of December receives exactly the same share as one who closed in January, provided both hold the same units.
- Under **`UNIT_DAYS_WEIGHTED`** each closed subscription is weighted by unit-days, being its `units_requested` multiplied by the whole days from the date of its `closed_at` through December 31 of the `tax_year`, inclusive of both endpoints. The share is this subscription's unit-days divided by the sum of unit-days over every `CLOSED` subscription on the trust. Closing date now drives the split, so two investors holding identical units but closing in different months receive different numbers from identical trust-level totals.

Issuing a statement moves it `DRAFT → ISSUED`, requires the statement to be `DRAFT` and its subscription still `CLOSED`, stamps `issued_at` from the logical clock, and renders the statement immutable. Tax-statement preparation and issuance are both exempt from posture gating: a frozen or winding-down trust must still be able to report to its owners.

### 3.9. Exit, Liquidation and the Successor Exchange

A `SponsorPrincipal` proposes an exit naming the `trust_id`, the `exit_mode` — `ASSET_SALE` or `SECTION_721_CONVERSION` — the `gross_price_cents` of the sale or contribution (at least 1), the `selling_costs_cents` of the transaction (zero or more), the `consent_threshold_pct` of issued units that must consent, expressed as a fraction between 0.0001 and 1.0000 inclusive, and the `expected_close_on` target closing date. The trust must be `OPERATING`. The event is created in status `PROPOSED` with `consented_units` at zero and every other computed figure empty. Exit events are listable and filterable by `trust_id`, `status` and `exit_mode`.

Each beneficial owner votes by recording a consent naming the `exit_event_id`, the `subscription_id` casting the vote and the `decision`, which is `CONSENT` or `WITHHOLD`. The acting `Investor`'s `X-User-ID` must equal the `investor_id` of the named subscription, that subscription must be in status `CLOSED`, and the exit event must still be `PROPOSED`. One vote per subscription: a second consent for the same `exit_event_id` and `subscription_id` pair is refused with `ERR_DUPLICATE_CONSENT`. The row snapshots the subscription's `units_requested` into `units_at_consent` and stamps `recorded_at` from the logical clock; a later rescission therefore cannot retroactively change a vote's weight. Consent recording is exempt from posture gating. Consents are listable and filterable by `exit_event_id`, `subscription_id` and `decision`.

Tallying the consents is the sponsor's act and moves the event `PROPOSED → APPROVED`. It requires the event to be `PROPOSED`, the trust to be `OPERATING`, and **at least one** consent row to exist: an empty consent set is not a zero-percent rejection, it is an untallied event, and it is refused with `ERR_NO_CONSENTS_RECORDED`. The `consented_units` is the sum of `units_at_consent` over rows whose `decision` is `CONSENT`; withheld rows count toward nothing. The reported `consent_pct` is the `consented_units` multiplied by ten thousand, divided by the trust's `units_issued`, rounded half up, then divided by ten thousand so it reads to four decimal places. The enforced test is exact integer cross-multiplication and does not round: the `consented_units` multiplied by ten thousand must be at least the threshold in basis points — the `consent_threshold_pct` multiplied by ten thousand and rounded half up — multiplied by the trust's `units_issued`. A tally landing exactly on the threshold passes. A tally short of the threshold is not an error: the request succeeds, the recomputed `consented_units` and `consent_pct` are stored and returned, but the event remains in `PROPOSED` and the trust is left entirely untouched, so more votes may arrive and the sponsor may tally again.

A successful tally sets `consented_units` and `consent_pct` and reaches through to the trust: the trust moves `OPERATING → WINDING_DOWN`, its `springing_llc_armed` flag is set true when the `exit_mode` is `SECTION_721_CONVERSION` and false otherwise, and its `posture` is recomputed to `FROZEN` because an `APPROVED` exit event now exists on it. From that moment ordinary trust business stops: only the exit close, the liquidating distribution, tax statements, consents and abandonment remain available. The sponsor may instead abandon a proposed exit with an optional `reason`, moving it `PROPOSED → ABANDONED`; abandonment leaves the trust's `status` and `posture` completely untouched, and is itself exempt from posture gating.

Closing the exit is the `Trustee`'s act and is the largest cascade in the system. It requires the event to be `APPROVED`, the trust to be `WINDING_DOWN`, and the trust's facility to be in status `FUNDED`. The distributable proceeds depend on the mode, and this is where the two modes diverge:

- Under **`ASSET_SALE`** a buyer pays cash and the facility is retired out of the proceeds, so `net_proceeds_cents` is the `gross_price_cents` minus the `selling_costs_cents` minus the facility's `principal_cents`.
- Under **`SECTION_721_CONVERSION`** the asset is contributed *subject to* the existing debt, so no payoff occurs and the principal is **not** deducted: `net_proceeds_cents` is simply the `gross_price_cents` minus the `selling_costs_cents`.

For identical `gross_price_cents` and `selling_costs_cents` the two modes therefore differ by exactly the facility's `principal_cents`. The reported `net_proceeds_per_unit_cents` is the `net_proceeds_cents` divided by the trust's `units_issued`, floored — and it is a reported figure only. The cash investors actually receive is allocated over the ledger balance by the allocation rules of §3.8, never by multiplying this per-unit number by anyone's units.

The order of operations inside the close is pinned, and each step depends on the ones before it:

1. A `SALE_PROCEEDS` entry is booked in the `OPERATING` bucket for the positive of `gross_price_cents` minus `selling_costs_cents`, with `source_kind` `EXIT`. Under `ASSET_SALE` a `LOAN_PAYOFF` entry is also booked in the `OPERATING` bucket for the negative of the facility's `principal_cents`; under `SECTION_721_CONVERSION` no payoff entry is written at all. Either way the facility moves `FUNDED → PAID_OFF`, because under the conversion the loan simply travels with the asset. The property moves `ACQUIRED → DISPOSED`.
2. The reserve bucket is swept into operating as a two-legged pair: a `REVERSAL` entry in the `RESERVE` bucket for the negative of the trust's remaining `reserve_balance_cents`, with `reversal_of_entry_id` **empty** and `source_kind` `EXIT`, and an equal positive entry in the `OPERATING` bucket. The sweep drives `reserve_balance_cents` to exactly zero. This is the one `REVERSAL` entry in the system that reverses no specific earlier entry, and its own signed amount therefore counts in full.
3. The liquidating amount is the trust's `operating_balance_cents` **after** steps 1 and 2 — everything left in the trust after the sale, the payoff and the sweep.
4. A distribution is created with `kind` `LIQUIDATING`, `period_start` equal to the event's `closed_at`, `period_end` equal to that instant plus one millisecond, status `DECLARED`, and `provisional_amount_cents` equal to the liquidating amount. That one-millisecond window is exempt from the period-overlap rule and the liquidating distribution is exempt from posture gating entirely, which it must be, since the trust is necessarily `FROZEN` by now. Paying it later follows the ordinary allocation rules of §3.8 unchanged, with the amount being its own `final_amount_cents`.
5. One successor exchange file is seeded per `CLOSED` subscription on the trust, taken in `closing_sequence_no` ascending order. Each successor file takes the subscription's `investor_id`; a `source_exit_event_id` pointing back at this exit event; a `qi_reference` formed as the literal text `SUCCESSOR-` immediately followed by that subscription's `closing_sequence_no` with no separator, so the first closed subscription yields `SUCCESSOR-1`; a `relinquished_closed_on` equal to the event's `closed_at`; a `relinquished_sale_price_cents` equal to the event's `gross_price_cents` multiplied by the subscription's `units_requested`, divided by the trust's `units_issued` and rounded half up; a `net_proceeds_cents` seeded the same way from the liquidating amount, because the allocation row this subscription will eventually receive is not yet known at seeding time; a `debt_retired_cents` seeded the same way from the facility's `principal_cents`; an `identification_rule` of `THREE_PROPERTY`; a `boot_tolerance_cents` of zero; and status `OPEN`. Each successor file's `identification_deadline` and `exchange_deadline` are then computed by the ordinary 45-day and 180-day rules, both clocks starting from the event's `closed_at` — so the exit that ends one exchange starts the next one on the same instant.
6. The event's `closed_at`, `net_proceeds_cents` and `net_proceeds_per_unit_cents` are set, the event moves `APPROVED → CLOSED`, and the trust reaches its own terminal state: `WINDING_DOWN → TERMINATED` under `ASSET_SALE`, or `WINDING_DOWN → CONVERTED_LLC` under `SECTION_721_CONVERSION`, the latter additionally requiring `springing_llc_armed` to be true. The trust's `version` advances by one.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 and the created resource in `data`. Endpoints that modify an existing resource, drive a state transition or perform a read return HTTP 200 and the affected or requested resource in `data`. Every list endpoint accepts `limit` and `offset` and returns the paginated envelope of §2.3. Every filter parameter listed below is optional; omitting all of them lists every row of that collection. Every foreign key declared on an entity is reverse-reachable through the matching filtered list, which is the only way to discover rows created by a cascade — ledger entries, distribution allocations and successor exchange files in particular.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| `POST` | `/_clock/set_current_utc` | Sets the server's logical clock from `to_iso8601` and returns `current_utc`. The startup default is exactly `2026-08-01T00:00:00Z`, and the server never reads real wall-clock time. | `PlatformAdmin` |
| `POST` | `/properties` | Registers a candidate replacement property under contract from `name`, `state_code`, `asset_type`, `purchase_price_cents`, `appraised_value_cents`, `annual_noi_cents`, `occupancy_rate` and `contract_close_deadline`. | `SponsorPrincipal` |
| `GET` | `/properties/{property_id}` | Reads one property, including its `depreciable_basis_cents` and `acquired_at`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `QualifiedIntermediary`, `PlatformAdmin` |
| `GET` | `/properties` | Lists properties, filterable by `state_code`, `asset_type` and `status`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `QualifiedIntermediary`, `PlatformAdmin` |
| `POST` | `/properties/{property_id}/acquire` | Closes the purchase, stamping `acquired_at` and computing `depreciable_basis_cents`. | `SponsorPrincipal` |
| `POST` | `/properties/{property_id}/expire-contract` | Records that the purchase contract lapsed unexercised, freezing the posture of every trust formed on the property. | `SponsorPrincipal` |
| `POST` | `/trusts` | Forms a Delaware statutory trust to hold one property from `property_id`, `trust_name`, `total_units`, `reserve_floor_cents` and `reserve_target_pct`. | `Trustee` |
| `GET` | `/trusts/{trust_id}` | Reads one trust, including its derived `operating_balance_cents`, `reserve_balance_cents`, `units_issued`, `equity_raised_cents`, `posture`, `springing_llc_armed` and `version`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `QualifiedIntermediary`, `PlatformAdmin` |
| `GET` | `/trusts` | Lists trusts, filterable by `property_id`, `status` and `posture`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `QualifiedIntermediary`, `PlatformAdmin` |
| `POST` | `/trusts/{trust_id}/open-funding` | Opens the trust for investor closings and copies `property_acquired_at` from the property. | `Trustee` |
| `GET` | `/trusts/{trust_id}/investor-report` | Computed read returning `trust_id`, `status`, `posture`, `units_issued`, `units_available`, `equity_raised_cents`, `operating_balance_cents`, `reserve_balance_cents`, `reserve_target_cents`, `reserve_variance_cents`, `distributions_paid_cents` and `closed_investor_count`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `POST` | `/trusts/{trust_id}/rent-postings` | Master tenant remits rent from `rent_kind` and `amount_cents`, booking a `RENT_RECEIPT` entry at the current logical instant. | `MasterTenant` |
| `POST` | `/trusts/{trust_id}/debt-service-payments` | Trustee pays scheduled interest from `amount_cents`, booking a `DEBT_SERVICE` entry at the current logical instant. | `Trustee` |
| `POST` | `/offerings` | Drafts the private placement offering from `trust_id`, `exemption_rule`, `unit_price_cents`, `min_units_per_investor`, `load_pct`, `closing_costs_cents`, `reserve_funding_pct` and `rescission_window_days`. | `SponsorPrincipal` |
| `GET` | `/offerings/{offering_id}` | Reads one offering, including `ppm_version`, `ppm_submitted_by_user_id`, `effective_at`, `initial_reserve_cents`, `target_equity_cents`, `sponsor_load_cents`, `units_committed`, `equity_committed_cents` and `version`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `QualifiedIntermediary`, `PlatformAdmin` |
| `GET` | `/offerings` | Lists offerings, filterable by `trust_id`, `status` and `exemption_rule`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `QualifiedIntermediary`, `PlatformAdmin` |
| `POST` | `/offerings/{offering_id}/submit-ppm` | Sponsor submits the memorandum named by `ppm_document_reference` for compliance review, recording `ppm_submitted_by_user_id`. | `SponsorPrincipal` |
| `POST` | `/offerings/{offering_id}/return-ppm` | Compliance returns the memorandum for revision with an optional `review_note`, incrementing `ppm_version`. | `ComplianceOfficer` |
| `POST` | `/offerings/{offering_id}/declare-effective` | Compliance declares the offering effective against `acknowledged_ppm_version`, pinning the grossed-up capital stack. | `ComplianceOfficer` |
| `POST` | `/offerings/{offering_id}/withdraw` | Compliance withdraws an unlaunched offering with an optional `reason`, rejecting its outstanding subscriptions. | `ComplianceOfficer` |
| `GET` | `/offerings/{offering_id}/capital-stack` | Computed read returning `offering_id`, `purchase_price_cents`, `closing_costs_cents`, `loan_principal_cents`, `initial_reserve_cents`, `net_acquisition_cents`, `base_need_cents`, `target_equity_cents`, `sponsor_load_cents`, `unit_capacity_cents`, `equity_committed_cents` and `equity_remaining_cents`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `POST` | `/investors` | Onboards a prospective beneficial owner from `legal_name`, `entity_type`, `accreditation_method`, `annual_income_cents`, `net_worth_cents` and `liquid_net_worth_cents`. | `SponsorPrincipal`, `PlatformAdmin` |
| `GET` | `/investors/{investor_id}` | Reads one investor, including `accreditation_status`, `accreditation_verified_at`, `accreditation_expires_at`, `suitability_status`, `suitability_cap_cents`, `suitability_offering_id` and `suitability_reviewed_by_user_id`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `GET` | `/investors` | Lists investors, filterable by `entity_type`, `accreditation_status`, `suitability_status` and `suitability_offering_id`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `POST` | `/investors/{investor_id}/verify-accreditation` | Compliance verifies accreditation against `evidence_reference`, setting the ninety-day expiry and leaving suitability untouched. | `ComplianceOfficer` |
| `POST` | `/investors/{investor_id}/lapse-accreditation` | Compliance records that a verification has aged out, leaving `suitability_status` and `suitability_cap_cents` unchanged. | `ComplianceOfficer` |
| `POST` | `/investors/{investor_id}/review-suitability` | Compliance reviews suitability from `decision` and `offering_id`, computing `suitability_cap_cents` and leaving accreditation untouched. | `ComplianceOfficer` |
| `POST` | `/exchange-files` | Opens a 1031 exchange file from `investor_id`, `qi_reference`, `relinquished_closed_on`, `relinquished_sale_price_cents`, `net_proceeds_cents`, `debt_retired_cents`, `identification_rule` and optional `boot_tolerance_cents`. | `QualifiedIntermediary` |
| `GET` | `/exchange-files/{exchange_file_id}` | Reads one exchange file, including `identification_deadline`, `exchange_deadline` and `source_exit_event_id`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `GET` | `/exchange-files` | Lists exchange files, filterable by `investor_id`, `source_exit_event_id`, `status` and `identification_rule`; successor files seeded by an exit close are discoverable only here. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `POST` | `/exchange-files/{exchange_file_id}/mark-expired` | Closes out a file whose identification or exchange deadline has passed, rejecting its outstanding subscriptions. | `QualifiedIntermediary` |
| `POST` | `/property-identifications` | Files an identification from `exchange_file_id`, `property_id` and `fair_market_value_cents`, assigning `identified_at` and `sequence_no`. | `QualifiedIntermediary` |
| `GET` | `/property-identifications/{identification_id}` | Reads one identification. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `GET` | `/property-identifications` | Lists identifications, filterable by `exchange_file_id`, `property_id` and `status`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `POST` | `/property-identifications/{identification_id}/revoke` | Withdraws an identification with an optional `reason` while the forty-five-day window is still open. | `QualifiedIntermediary` |
| `POST` | `/subscriptions` | Reserves units from `offering_id`, `investor_id`, `exchange_file_id`, `units_requested` and the concurrency token `expected_offering_version`, computing `investment_amount_cents` and `boot_cents`. | `SponsorPrincipal` |
| `GET` | `/subscriptions/{subscription_id}` | Reads one subscription, including `investment_amount_cents`, `boot_cents`, `closing_sequence_no`, `closed_at` and `rescission_deadline`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `GET` | `/subscriptions` | Lists subscriptions, filterable by `offering_id`, `investor_id`, `exchange_file_id` and `status`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `QualifiedIntermediary`, `PlatformAdmin` |
| `POST` | `/subscriptions/{subscription_id}/close` | Closes the subscription into the trust; the head of the four-hop closing cascade, barred to the officer who approved the investor's suitability. | `SponsorPrincipal` |
| `POST` | `/subscriptions/{subscription_id}/reject` | Compliance rejects a reserved or revision-required subscription with an optional `reason`. | `ComplianceOfficer` |
| `POST` | `/subscriptions/{subscription_id}/rescind` | Investor rescinds a closed subscription inside its rescission window, booking the compensating reversal and renumbering the remaining closings. | `Investor` |
| `POST` | `/loan-facilities` | Commits trust-level debt from `trust_id`, `lender_name`, `principal_cents`, `rate_bps`, `recourse_type` and `maturity_on`, computing `ltv_pct` and `dscr`. | `Trustee` |
| `GET` | `/loan-facilities/{loan_id}` | Reads one facility, including `ltv_pct`, `dscr`, `repriced_count` and `funded_at`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `GET` | `/loan-facilities` | Lists facilities, filterable by `trust_id`, `status` and `recourse_type`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `POST` | `/loan-facilities/{loan_id}/reprice` | Re-cuts committed debt terms from `principal_cents`, `rate_bps` and `recourse_type`; the head of the three-hop repricing cascade, and a prohibited refinancing once the offering period has ended. | `Trustee` |
| `POST` | `/loan-facilities/{loan_id}/fund` | Draws the facility at closing, booking `LOAN_PROCEEDS` into the operating bucket. | `Trustee` |
| `POST` | `/master-leases` | Drafts the master lease from `trust_id`, `master_tenant_user_id`, `term_start_on`, `term_end_on`, `base_rent_annual_cents` and `supplemental_rent_annual_cents`. | `Trustee` |
| `GET` | `/master-leases/{lease_id}` | Reads one master lease, including `executed_at`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `PlatformAdmin` |
| `GET` | `/master-leases` | Lists master leases, filterable by `trust_id`, `status` and `master_tenant_user_id`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `PlatformAdmin` |
| `POST` | `/master-leases/{lease_id}/execute` | Executes the master lease, unblocking rent postings and distribution declarations. | `Trustee` |
| `POST` | `/master-leases/{lease_id}/terminate` | Terminates an executed master lease with an optional `reason`. | `Trustee` |
| `GET` | `/ledger-entries/{ledger_entry_id}` | Reads one ledger entry, including `entry_type`, `bucket`, `amount_cents`, `occurred_at`, `memo`, `source_kind` and `reversal_of_entry_id`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `PlatformAdmin` |
| `GET` | `/ledger-entries` | Lists ledger entries, filterable by `trust_id`, `reversal_of_entry_id`, `entry_type`, `bucket` and `source_kind`; cascade-booked entries are discoverable only here. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `PlatformAdmin` |
| `POST` | `/capital-needs` | Records a capital need from `trust_id`, `need_type`, `amount_cents` and `needed_by`. | `Trustee`, `MasterTenant` |
| `GET` | `/capital-needs/{capital_need_id}` | Reads one capital need, including `funding_source` and `funded_at`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `PlatformAdmin` |
| `GET` | `/capital-needs` | Lists capital needs, filterable by `trust_id`, `status`, `need_type` and `funding_source`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `MasterTenant`, `PlatformAdmin` |
| `POST` | `/capital-needs/{capital_need_id}/fund` | Funds a capital need from `funding_source`; `RESERVE` draws the trust reserve, `MASTER_TENANT` funds it outside the books, and `CAPITAL_CALL` is never permitted. | `Trustee`, `MasterTenant` |
| `POST` | `/capital-needs/{capital_need_id}/void` | Voids a capital need with an optional `reason`, compensating a reserve draw with an exact reversal. | `Trustee` |
| `POST` | `/distributions` | Declares a distribution from `trust_id`, `kind`, `period_start`, `period_end` and the concurrency token `expected_trust_version`, computing `provisional_amount_cents`. | `Trustee` |
| `GET` | `/distributions/{distribution_id}` | Reads one distribution, including `provisional_amount_cents`, `final_amount_cents`, `reconciliation_delta_cents`, `declared_at` and `paid_at`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `GET` | `/distributions` | Lists distributions, filterable by `trust_id`, `status` and `kind`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `POST` | `/distributions/{distribution_id}/pay` | Pays the distribution on the final-cash measurement and splits it across closed subscriptions by the round-then-sweep allocation. | `Trustee` |
| `POST` | `/distributions/{distribution_id}/void` | Voids a declared distribution with an optional `reason`, releasing its period. | `Trustee` |
| `GET` | `/distribution-allocations/{allocation_id}` | Reads one allocation row, including `units`, `raw_share_cents`, `allocated_cents` and `residual_adjustment_cents`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `GET` | `/distribution-allocations` | Lists allocations, filterable by `distribution_id` and `subscription_id`; cascade-created allocations are discoverable only here. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `POST` | `/tax-statements` | Prepares a grantor-trust statement from `trust_id`, `subscription_id`, `tax_year` and `allocation_variant`, computing `rental_income_cents`, `interest_expense_cents`, `depreciation_cents` and `net_taxable_income_cents`. | `SponsorPrincipal` |
| `GET` | `/tax-statements/{tax_statement_id}` | Reads one tax statement, including `issued_at`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `GET` | `/tax-statements` | Lists tax statements, filterable by `trust_id`, `subscription_id`, `tax_year`, `status` and `allocation_variant`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `POST` | `/tax-statements/{tax_statement_id}/issue` | Issues the statement to the beneficial owner, stamping `issued_at` and rendering it immutable. | `SponsorPrincipal` |
| `POST` | `/exit-events` | Proposes an exit from `trust_id`, `exit_mode`, `gross_price_cents`, `selling_costs_cents`, `consent_threshold_pct` and `expected_close_on`. | `SponsorPrincipal` |
| `GET` | `/exit-events/{exit_event_id}` | Reads one exit event, including `consented_units`, `consent_pct`, `net_proceeds_cents`, `net_proceeds_per_unit_cents` and `closed_at`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `GET` | `/exit-events` | Lists exit events, filterable by `trust_id`, `status` and `exit_mode`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `POST` | `/exit-events/{exit_event_id}/tally-consents` | Tallies recorded consents against the threshold; on success the trust begins winding down and its posture freezes. | `SponsorPrincipal` |
| `POST` | `/exit-events/{exit_event_id}/abandon` | Abandons a proposed exit with an optional `reason`, leaving the trust untouched. | `SponsorPrincipal` |
| `POST` | `/exit-events/{exit_event_id}/close` | Closes the exit: books proceeds, retires or transfers the debt, disposes the property, sweeps the reserve, declares the liquidating distribution and seeds one successor exchange file per closed subscription. | `Trustee` |
| `POST` | `/exit-consents` | Beneficial owner records a vote from `exit_event_id`, `subscription_id` and `decision`, snapshotting `units_at_consent` and `recorded_at`. | `Investor` |
| `GET` | `/exit-consents/{exit_consent_id}` | Reads one consent row. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |
| `GET` | `/exit-consents` | Lists consents, filterable by `exit_event_id`, `subscription_id` and `decision`. | `SponsorPrincipal`, `ComplianceOfficer`, `Trustee`, `Investor`, `PlatformAdmin` |

## 5. Error Code Catalogue

Every error response carries one of the following identifiers in the `error_id` field of the error envelope described in §2.2, together with the HTTP status shown. When more than one condition is violated by a single request, the identifier reported is the one belonging to the lowest-numbered rung of the rejection ladder in §2.10, and no side effect of the request is applied.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_TRUST_NOT_FOUND` | 404 |
| `ERR_OFFERING_NOT_FOUND` | 404 |
| `ERR_INVESTOR_NOT_FOUND` | 404 |
| `ERR_EXCHANGE_FILE_NOT_FOUND` | 404 |
| `ERR_IDENTIFICATION_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_MASTER_LEASE_NOT_FOUND` | 404 |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 |
| `ERR_CAPITAL_NEED_NOT_FOUND` | 404 |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_TAX_STATEMENT_NOT_FOUND` | 404 |
| `ERR_EXIT_EVENT_NOT_FOUND` | 404 |
| `ERR_EXIT_CONSENT_NOT_FOUND` | 404 |
| `ERR_STALE_OFFERING_VERSION` | 412 |
| `ERR_STALE_TRUST_VERSION` | 412 |
| `ERR_PROPERTY_INVALID_STATE` | 409 |
| `ERR_TRUST_INVALID_STATE` | 409 |
| `ERR_TRUST_FROZEN` | 409 |
| `ERR_TRUST_RESTRICTED` | 409 |
| `ERR_OFFERING_INVALID_STATE` | 409 |
| `ERR_OFFERING_NOT_EFFECTIVE` | 409 |
| `ERR_EXCHANGE_FILE_INVALID_STATE` | 409 |
| `ERR_IDENTIFICATION_INVALID_STATE` | 409 |
| `ERR_SUBSCRIPTION_INVALID_STATE` | 409 |
| `ERR_LOAN_INVALID_STATE` | 409 |
| `ERR_MASTER_LEASE_INVALID_STATE` | 409 |
| `ERR_MASTER_LEASE_NOT_EXECUTED` | 409 |
| `ERR_CAPITAL_NEED_INVALID_STATE` | 409 |
| `ERR_DISTRIBUTION_INVALID_STATE` | 409 |
| `ERR_TAX_STATEMENT_INVALID_STATE` | 409 |
| `ERR_EXIT_INVALID_STATE` | 409 |
| `ERR_PROPERTY_NOT_ACQUIRED` | 409 |
| `ERR_PROPERTY_CONTRACT_EXPIRED` | 422 |
| `ERR_SUITABILITY_NOT_APPROVED` | 422 |
| `ERR_ACCREDITATION_EXPIRED` | 422 |
| `ERR_INVESTOR_NOT_ACCREDITED` | 422 |
| `ERR_CAPITAL_CALL_PROHIBITED` | 422 |
| `ERR_REFINANCING_PROHIBITED` | 422 |
| `ERR_RECOURSE_DEBT_PROHIBITED` | 422 |
| `ERR_MULTIPLE_LOANS_PROHIBITED` | 409 |
| `ERR_NEW_LEASE_PROHIBITED` | 422 |
| `ERR_STRUCTURAL_CAPEX_PROHIBITED` | 422 |
| `ERR_ACCREDITATION_METHOD_NOT_PERMITTED` | 422 |
| `ERR_RESERVE_INSUFFICIENT` | 422 |
| `ERR_OPERATING_CASH_INSUFFICIENT` | 422 |
| `ERR_LTV_LIMIT_EXCEEDED` | 422 |
| `ERR_DSCR_BELOW_MINIMUM` | 422 |
| `ERR_IDENTIFICATION_WINDOW_CLOSED` | 422 |
| `ERR_EXCHANGE_DEADLINE_PASSED` | 422 |
| `ERR_RESCISSION_WINDOW_CLOSED` | 409 |
| `ERR_DISTRIBUTION_PERIOD_NOT_ENDED` | 422 |
| `ERR_DISTRIBUTION_PERIOD_OVERLAP` | 409 |
| `ERR_LEASE_TERM_OVERLAP` | 409 |
| `ERR_PROPERTY_ALREADY_TRUSTED` | 409 |
| `ERR_DUPLICATE_IDENTIFICATION` | 409 |
| `ERR_DUPLICATE_CONSENT` | 409 |
| `ERR_DUPLICATE_TAX_STATEMENT` | 409 |
| `ERR_EXCHANGE_FILE_INVESTOR_MISMATCH` | 422 |
| `ERR_SUITABILITY_OFFERING_MISMATCH` | 422 |
| `ERR_IDENTIFICATION_MISSING_FOR_TRUST` | 422 |
| `ERR_PPM_VERSION_STALE` | 409 |
| `ERR_IDENTIFICATION_RULE_VIOLATION` | 422 |
| `ERR_BELOW_MINIMUM_INVESTMENT` | 422 |
| `ERR_SUITABILITY_CAP_EXCEEDED` | 422 |
| `ERR_BOOT_EXCEEDS_TOLERANCE` | 422 |
| `ERR_OFFERING_OVERSUBSCRIBED` | 422 |
| `ERR_OFFERING_CAPACITY_SHORTFALL` | 422 |
| `ERR_NO_CONSENTS_RECORDED` | 422 |
