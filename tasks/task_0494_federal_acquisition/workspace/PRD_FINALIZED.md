# Federal Acquisition API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Federal Acquisition API, a system that models the end-to-end lifecycle of government contracting in the spirit of SAM.gov registration and the Federal Acquisition Regulation (FAR). The platform carries a procurement from the publication of a solicitation (an RFP, RFQ, or IFB), through vendor registration and set-aside eligibility, proposal submission and structured evaluation, award, and the realization of that award into an administered contract with line items, invoices, modifications, option years, performance ratings, protests, and closeout.

The domain is defined by two forces in tension. The first is compliance: every consequential action — opening a solicitation, submitting a proposal, scoring it, making an award, approving an invoice, exercising an option — is gated by eligibility checks, deadlines, fiscal ceilings, and a strict separation of duties between the official who chairs an evaluation and the official who signs the resulting award. The second is multi-party negotiation across time: vendors, contracting officers, and read-only auditors interact with the same records, those records advance through branching and occasionally cyclic state machines, and a single resolved protest can compensate an entire chain of downstream entities back to an earlier point. Because every deadline, expiry, and option window is measured against a server-controlled logical clock rather than wall-clock time, the system is fully deterministic and reproducible for testing.

This specification is the single source of truth for the API's behavior. It defines the data model implicitly through the workflows that read and write it, the precise arithmetic of every computed amount and score, the order in which validations fire, and the exact error each failed check returns.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API. The business workflows in Section 3 build on the guarantees established here.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly three roles, spelled precisely as follows: `ContractingOfficer`, `Vendor`, and `Auditor`.

A `ContractingOfficer` is the government official who drives the procurement: they create and steer solicitations, add evaluation factors, begin and finalize evaluations, score proposals, make awards, administer contracts and their line items, propose and approve modifications, approve or reject invoices, review and resolve protests, file performance reports, and manage vendor registration lifecycle transitions other than the vendor-initiated ones. When `X-User-Role` is `ContractingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`, but it does record it where a transition requires it: finalizing an evaluation records the acting officer as the evaluation chair on the solicitation, and making an award records the acting officer in the award's `awarded_by_user_id` field. These recorded identifiers are what the segregation-of-duties rule later compares.

A `Vendor` is an offeror or awardee acting on its own behalf. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `VendorRegistration`; ownership checks on any resource that references a `VendorRegistration` compare the resource's vendor foreign key to `X-User-ID`. A vendor self-serves its own registration (creating and activating it), its proposals (creating, scoring, and submitting them), its invoices, and its protests (filing and withdrawing them).

An `Auditor` is a read-only oversight role, modeled on bodies such as the GAO or an Inspector General. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. An auditor may read every resource in the system but may mutate nothing.

All three roles may perform every read (GET) operation. Attaching a factor score to a proposal is permitted to both `Vendor` and `ContractingOfficer`. Every other write is restricted as described in the workflows of Section 3 and summarized in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a workflow states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order.

List responses always carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.7.

Most entities — vendor registrations, solicitations, proposals, factor scores, awards, contracts, contract line items, invoices, modifications, protests, and CPARS performance reports — carry the full set of `id`, `created_at`, `updated_at`, and `version`. The lone exception is the `EvaluationFactor`: a factor carries only `id` and `created_at`. It has neither an `updated_at` field nor a `version` field, because once attached to a draft solicitation a factor is not independently mutated.

All time-sensitive comparisons in the system — submission deadlines, registration expiry, and option-exercise windows — are evaluated against a single server-controlled **logical clock**, never against wall-clock time. On server startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly moved it stays at that default and never falls back to real time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant and reports the new value as `now_utc`. Every deadline, expiry, and window check elsewhere in this document reads this clock.

### 2.5. Hierarchical Consistency and Cascading Side Effects

When an operation changes one resource, the system also performs every dependent change the same operation implies, in the same logical transaction, and bumps the `version` and refreshes the `updated_at` of every entity it touches. These cascades are not optional follow-ups; they are part of the operation's contract and are detailed in the workflows of Section 3.

Three cascades are especially deep and must be implemented exactly. First, when an award is made, the awarding operation does not merely create the `Award`: it drives the solicitation to `AWARDED` and records its winning proposal, drives the winning proposal to `AWARDED`, and reclassifies every other still-live proposal of that solicitation as `REJECTED`. Second, when a contract is closed out, the closeout recomputes the awardee vendor's performance index from scratch. Third, when a protest is sustained, an extensive compensation cascade unwinds the award and everything beneath it back to the pre-award position; this is described in full in §3.6. In each case the parent and every affected child are independently mutated, each receiving an incremented `version` and a fresh `updated_at`.

### 2.6. Nested Resource Retrieval and Referential Existence

Many paths address a resource nested beneath a parent, and many request bodies name resources by foreign key. In all cases, the existence of every referenced resource is validated left-to-right: a path or body that names a parent and then a child is checked parent-first, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` before any later identifier is examined. This existence sweep precedes business-rule evaluation, so a request that points at a missing solicitation is rejected as not found before the system considers, for example, whether a deadline has passed.

### 2.7. Optimistic Concurrency Control

Two create operations are guarded by optimistic concurrency control so that a client cannot build on a parent it has not actually observed in its current form.

Creating an award against a solicitation requires the request body to carry `expected_solicitation_version`, the version of the solicitation the client last read. If that value does not match the target solicitation's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Because finalizing, amending, re-opening, and awarding all advance a solicitation's version, a second award attempt that still carries a pre-finalization version is working from a superseded view and is stopped on the stale version rather than on a state read.

Creating an invoice against a contract requires the request body to carry `expected_contract_version`, the version of the contract the client last read. If that value does not match the contract's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Because both invoice approvals and modification approvals bump the contract's version (recomputing cumulative invoiced amount and obligated amount respectively), a creator working from a contract view that has since been superseded is rejected on the stale version.

No other endpoint takes a version field, and no other endpoint performs an OCC check.

### 2.8. Evaluation Methods, Scoring, and Acceptability

Each solicitation is evaluated under one of two methods, derived from its vehicle. A solicitation of vehicle type `RFP` uses the `TRADEOFF` method, in which proposals are ranked by a combined value score that balances technical merit against price. A solicitation of vehicle type `RFQ` or `IFB` uses the `LPTA` method (lowest-price technically-acceptable), in which only acceptability matters for merit and the lowest-priced acceptable offer wins. The method is fixed when the solicitation opens.

Acceptability is a hard floor expressed through the constant **70**, the minimum acceptable raw score on any single non-price factor. A proposal is acceptable only if every one of its non-price factor scores is at least 70; if any non-price factor score is below 70, the proposal is unacceptable. Price factors never contribute to this acceptability test and never contribute to merit. The precise arithmetic of merit and value scores lives in §3.3.

### 2.9. Monetary Amounts, Scores, and Precision

All monetary amounts in the system — proposed prices, contract values, fees, invoice amounts, and ceilings — are stored and computed as integer cents. Where a fee or amount requires division, the result is rounded to the nearest whole cent using the round-half-up convention, and the workflows in Section 3 pin the exact order in which rounding occurs so that no two implementations diverge by a cent.

Two computed quantities are decimal scores rather than cents: a proposal's merit and value scores, and a vendor's performance index. Each is carried to exactly two decimal places using round-half-up. A vendor's performance index, when the vendor has no qualifying performance report, is the explicit value `null` rather than zero.

### 2.10. Fiscal Discipline: Obligation Ceilings and Funding Posture

Every contract carries an obligation ceiling and an independent funding posture that together enforce that the government never pays beyond what it has obligated. The obligated amount is the live ceiling; the funding posture records whether cumulative approved payments have caught up to that ceiling. A contract whose cumulative approved invoice amount has reached its obligated amount is said to have reached its ceiling, which permanently blocks the exercise of new option years until the ceiling is raised by an approved funding modification. The exact formulas for the obligated amount and cumulative invoiced amount, and the precise point at which the funding posture flips, are given in §3.5.

## 3. Business Logic & Workflows

This section narrates the procurement lifecycle from registration through closeout. Input parameters, thresholds, and cascade rules are distributed across the subsections in which they make business sense; a complete implementation of any one operation may require rules stated in more than one place.

### 3.1. Vendor Registration and SAM Eligibility

The lifecycle begins with a vendor establishing its registration. A `Vendor` creates a registration by supplying its `legal_name`, its `uei`, its `employee_count`, an optional list of `set_aside_certifications`, and its `registration_expires_at`. A new registration is born in `DRAFT` with `sam_status` defaulting to `DRAFT`. The `uei` must be exactly 12 alphanumeric characters. The `employee_count` must be zero or greater. The `set_aside_certifications` field, when supplied, is a subset of the certifications `EIGHT_A`, `SDVOSB`, `WOSB`, and `HUBZONE`; when omitted it defaults to an empty list. The `registration_expires_at` is the ISO 8601 UTC instant at which SAM coverage lapses, and it is compared against the logical clock wherever eligibility is tested. A vendor's `performance_index` is a computed field that starts as `null` and is described in §3.7.

Activating a registration moves it from `DRAFT` to `ACTIVE`, transitioning `sam_status` to `ACTIVE`. Activation is permitted only when the `uei` is exactly 12 alphanumeric characters, when no other registration holding the same UEI (compared case-insensitively) currently has a `sam_status` of either `ACTIVE` or `EXPIRED`, and when the `registration_expires_at` lies strictly after the current logical clock. A duplicate UEI at activation is rejected with `ERR_DUPLICATE_UEI`. Successful activation increments the registration's `version`.

A registration that has lapsed sits in `EXPIRED`. A contracting officer can expire an active registration, moving `ACTIVE` to `EXPIRED` and setting `sam_status` to `EXPIRED`. A vendor may revive an expired registration back to `ACTIVE` by activating it again; on this revival path the vendor supplies a renewed `registration_expires_at` in the activate body, and the revival is permitted only when that renewed expiry lies strictly after the current logical clock and when no other registration holding the same UEI is in `ACTIVE` or `EXPIRED`. This `EXPIRED` to `ACTIVE` revival, in addition to the ordinary `DRAFT` to `ACTIVE` path, means the registration machine is cyclic rather than strictly linear. Both expiry and revival increment the registration's `version`.

A contracting officer may debar a vendor by excluding it. Exclusion is reachable from either `ACTIVE` or `EXPIRED`, sets `sam_status` to `EXCLUDED`, and increments the `version`. `EXCLUDED` is terminal: an excluded registration has no further transitions.

### 3.2. Building and Opening a Solicitation

A `ContractingOfficer` opens the buy by creating a solicitation, supplying its `title`, its `vehicle_type`, an optional `set_aside_type`, a `naics_size_threshold`, an `open_at`, and a `close_at`. The `vehicle_type` is one of `RFP`, `RFQ`, or `IFB`. The `set_aside_type` is one of `NONE`, `SMALL_BUSINESS`, `EIGHT_A`, `SDVOSB`, `WOSB`, or `HUBZONE`, defaulting to `NONE`. The `naics_size_threshold` is the employee size standard, at least 1, under which a vendor counts as small-business eligible. The `open_at` is the instant the solicitation becomes available for proposals and the `close_at` is the proposal submission deadline; `close_at` must lie strictly after `open_at`. A new solicitation is born in `DRAFT` with `status` defaulting to `DRAFT`, an `amendment_count` of 0, and a `winning_proposal_id` of `null`. Its `evaluation_method` is computed later, at open time.

Before a solicitation can open, the contracting officer attaches one or more evaluation factors to it while it is still in `DRAFT`. Each factor records the `solicitation_id` it belongs to, a `name`, a `kind`, and a `weight`. The `kind` is one of `TECHNICAL`, `PAST_PERFORMANCE`, or `PRICE`, and there must be exactly one `PRICE` factor per solicitation. The `weight` lies between 0 and 1 inclusive; the price factor's weight is ignored by merit scoring, while the weights of the non-price factors must sum to exactly 1.0.

Opening a solicitation drives `DRAFT` to `OPEN`, setting `status` to `OPEN`. Opening is permitted only when at least one evaluation factor exists for the solicitation, exactly one factor of kind `PRICE` exists, the sum of the weights across the non-price factors equals 1.0, and the `open_at` lies at or before the current logical clock. A solicitation that lacks its single price factor or whose non-price weights do not sum to 1.0 is rejected with `ERR_FACTOR_WEIGHTS_INVALID`. On a successful open, the system sets the `evaluation_method` to `TRADEOFF` when the `vehicle_type` is `RFP`, and to `LPTA` otherwise, and increments the solicitation's `version`.

An open solicitation may be amended. Amending drives `OPEN` to `AMENDED`, sets `status` to `AMENDED`, increments `amendment_count` by one, and increments the `version`; it is permitted only while the current logical clock is at or before `close_at`. An amended solicitation can be re-opened, driving `AMENDED` back to `OPEN`; this re-open is likewise permitted only while the clock is at or before `close_at`, and it increments the `version`. The `OPEN`-to-`AMENDED`-to-`OPEN` loop makes the solicitation machine cyclic.

When the deadline has arrived, the solicitation is closed. Closing is reachable from either `OPEN` or `AMENDED`, drives the status to `CLOSED`, and is permitted only when the current logical clock is at or after `close_at`. On closing, every proposal of the solicitation that is in `SUBMITTED` status remains in `SUBMITTED` and thereby eligible for evaluation. Closing increments the solicitation's `version`.

A solicitation may be cancelled outright. Cancellation is reachable from `DRAFT` or from `OPEN`, sets the status to `CANCELLED`, and increments the `version`. When an `OPEN` solicitation is cancelled, every proposal of that solicitation in `SUBMITTED`, `UNDER_EVALUATION`, `ACCEPTABLE`, or `UNACCEPTABLE` status cascades to `WITHDRAWN`. `CANCELLED` and `AWARDED` are the terminal states of the solicitation machine.

### 3.3. Proposals, Factor Scores, and the Evaluation Fork

A `Vendor` drafts a proposal by naming the `solicitation_id` it responds to, its own `vendor_id`, and its `total_price_cents`. The proposed price must be zero or greater. A new proposal is born in `DRAFT` with `status` defaulting to `DRAFT`; its `pinned_vendor_version`, `merit_score`, and `value_score` all begin as `null`. While the proposal is in `DRAFT`, factor scores are attached to it, and they may also be revised while the proposal is `UNACCEPTABLE` (the mechanism that satisfies the re-evaluation precondition in the paragraph below); attaching a score to a proposal in any other status is not permitted. Each factor score names the `proposal_id` it belongs to, the `factor_id` it scores against, and a `raw_score` in the inclusive range 0 to 100. A factor score whose `raw_score` falls outside that range is rejected as a malformed request. A given factor is scored at most once per proposal: attaching a score for a `factor_id` that the proposal already has a score for replaces that existing score's `raw_score` in place (refreshing it rather than creating a second score for the same factor) so that merit and acceptability read the revised value.

Submitting a proposal drives `DRAFT` to `SUBMITTED`. Submission is gated by a cluster of preconditions that fire in priority order and that are themselves distributed below and in §3.8. The parent solicitation must be in `OPEN` or `AMENDED` status. The current logical clock must be at or before the solicitation's `close_at`; a submission past the deadline is rejected with `ERR_DEADLINE_PASSED`. The submitting vendor's registration must have a `sam_status` of `ACTIVE` and a `registration_expires_at` strictly after the current logical clock; a submission from a vendor that is not active or whose registration has lapsed is rejected with `ERR_REGISTRATION_NOT_ACTIVE`. A factor score must already exist for every evaluation factor of the solicitation. On a successful submission, the system sets `status` to `SUBMITTED`, captures the vendor's current registration `version` into the proposal's `pinned_vendor_version` so that a later staleness check at award time has a reference point, and increments the proposal's `version`.

Set-aside eligibility is also checked at submission. If the solicitation's `set_aside_type` is `SMALL_BUSINESS`, the vendor's `employee_count` must be at most the solicitation's `naics_size_threshold` (the comparison is inclusive). If the `set_aside_type` is one of the named programs — `EIGHT_A`, `SDVOSB`, `WOSB`, or `HUBZONE` — the vendor must hold the matching certification in its `set_aside_certifications`. A vendor that fails either form of the set-aside test is rejected with `ERR_SET_ASIDE_INELIGIBLE`.

Once the solicitation is closed, each submitted proposal enters evaluation. Beginning evaluation drives `SUBMITTED` to `UNDER_EVALUATION` and is permitted only when the parent solicitation's status is `CLOSED`; it increments the proposal's `version`. A proposal that was found unacceptable can be sent back through evaluation: beginning evaluation again drives `UNACCEPTABLE` back to `UNDER_EVALUATION`, permitted only when the parent solicitation is `CLOSED` and the factor scores have been revised since the prior scoring. This `UNACCEPTABLE`-to-`UNDER_EVALUATION` loop makes the proposal machine cyclic as well.

Scoring a proposal under evaluation forks it. If every non-price factor score is at least 70, the proposal is driven to `ACCEPTABLE`; if at least one non-price factor score is below 70, it is driven to `UNACCEPTABLE`. The two branches carry deliberately different side effects and must be implemented with equal care. On the `ACCEPTABLE` branch, the system recomputes the proposal's `merit_score`, additionally recomputes its `value_score` when the solicitation's evaluation method is `TRADEOFF`, and increments the `version`. On the `UNACCEPTABLE` branch, the system sets both `merit_score` and `value_score` to `null` and increments the `version`.

The **merit score** is a weighted technical-merit figure computed over the proposal's non-price factor scores only; the price factor is excluded. For each non-price factor score, multiply its `raw_score` by the `weight` of the factor it scores, and sum those products across all non-price factor scores; because the non-price weights sum to 1.0 (enforced at open), this raw sum is on the same 0-to-100 scale as the inputs. The merit score is that sum rounded half-up to two decimal places and then clamped to the range 0 to 100 inclusive. Under `LPTA`, the merit score is still computed and stored, but the award selector ignores it — `LPTA` selects the lowest `total_price_cents` among acceptable proposals rather than the highest merit.

The **value score** is computed only when the evaluation method is `TRADEOFF`; under `LPTA` it stays `null`. It blends merit against a normalized price, weighting merit at **0.80** and price at **0.20**. First take the minimum `total_price_cents` among the acceptable proposals of the solicitation (the proposal currently being scored is included in this pool). The normalized price for the scored proposal is that minimum price divided by the scored proposal's own `total_price_cents`, multiplied by 100, rounded half-up to two decimal places — so the lowest-priced offer earns the full 100 and pricier offers earn proportionally less. The order of computation is pinned and must be followed exactly: compute the merit score and round it to two decimal places first, then compute the normalized price and round it to two decimal places, and only then combine them by multiplying the rounded merit score by 0.80, multiplying the rounded normalized price by 0.20, summing the two products, and rounding that sum half-up to two decimal places to obtain the value score. Under `TRADEOFF` the value score is the award ranking key and the highest value wins; under `LPTA` the value score is absent and ranking uses `total_price_cents` ascending.

### 3.4. Award and Segregation of Duties

Before any award can be made, the contracting officer finalizes the evaluation, driving the solicitation from `CLOSED` to `EVALUATED`. Finalization is permitted only when every proposal that was in `SUBMITTED` has been evaluated to either `ACCEPTABLE` or `UNACCEPTABLE`, and when at least one proposal is `ACCEPTABLE`. On finalization, the system sets `status` to `EVALUATED`, records the acting operator's identifier as the solicitation's evaluation chair for the later segregation-of-duties check, and increments the `version`.

Making an award is the procurement's pivotal write. The contracting officer supplies the `solicitation_id`, the `proposal_id` of the winning offer, and `expected_solicitation_version`. The named proposal must belong to the named solicitation and must be in `ACCEPTABLE` status; a proposal that is not eligible on either count is rejected with `ERR_PROPOSAL_NOT_ELIGIBLE`. The award is also subject to **segregation of duties**: the operator making the award, identified by `X-User-ID` and recorded as `awarded_by_user_id`, must not be the same operator who finalized the evaluation of that solicitation (the recorded evaluation chair). An award attempted by the evaluation chair is rejected with `ERR_SEGREGATION_OF_DUTIES`. The OCC guard of §2.7 also applies here: a mismatched `expected_solicitation_version` is rejected with `ERR_STALE_VERSION`.

When the award succeeds, the system creates the `Award` in `AWARDED` status and runs the award cascade as a single transaction. The solicitation is driven from `EVALUATED` to `AWARDED`, its `winning_proposal_id` is set to the awarded proposal, and its `version` increments. The winning proposal is driven from `ACCEPTABLE` to `AWARDED`. Every other proposal of that solicitation that is in `ACCEPTABLE`, `UNACCEPTABLE`, or `SUBMITTED` status cascades to `REJECTED`. The winning proposal and each rejected sibling each have their `version` incremented.

### 3.5. Contract Administration: CLINs, Invoices, Modifications, and Fiscal Limits

An award is realized into a contract. A `ContractingOfficer` creates a contract by naming the `award_id` it realizes, the `contract_type`, the `base_value_cents`, and, for cost-reimbursement work, the `total_estimated_cost_cents` and `fixed_fee_cents`. The `contract_type` is either `FFP` (firm-fixed-price) or `CPFF` (cost-plus-fixed-fee). For a `CPFF` contract the `total_estimated_cost_cents` must be greater than 0 and the `fixed_fee_cents` must be zero or greater; both are required for `CPFF` and ignored for `FFP`. A `CPFF` contract created without its `total_estimated_cost_cents` or `fixed_fee_cents` is rejected with `ERR_VALIDATION`. The `base_value_cents` is the funded base-period ceiling and must be zero or greater. On creation the contract is born in lifecycle status `ACTIVE` with funding posture `WITHIN_CEILING`, its `obligated_amount_cents` set equal to its `base_value_cents`, its `cumulative_invoiced_cents` at 0, and its `vendor_id` copied from the winning proposal's vendor. A contract carries two parallel, independently evolving dimensions: its `lifecycle_status` (`ACTIVE`, `COMPLETE`, `CLOSED`, or `TERMINATED`) and its `funding_posture` (`WITHIN_CEILING` or `CEILING_REACHED`).

For firm-fixed-price work the contracting officer adds contract line items. Each CLIN records its parent `contract_id`, a `clin_number`, a `unit_price_cents`, and a `funded_qty`, and begins with a `delivered_qty` of 0. The `clin_number` must be unique within its contract; a duplicate is rejected with `ERR_DUPLICATE_CLIN`. The `unit_price_cents` is the firm unit price, required for `FFP`, and must be zero or greater; the `funded_qty` is the funded quantity of units and must be zero or greater. The `delivered_qty` accumulates the units billed across the CLIN's approved invoices.

A `Vendor` submits an invoice (a WAWF submission) against a contract, supplying the `contract_id`, the `expected_contract_version` required by the OCC guard of §2.7, and a payload shaped to the contract type. A firm-fixed-price invoice must carry a `clin_id` and an `invoiced_qty` and must not carry `allowable_cost_cents`; a cost-plus invoice must carry `allowable_cost_cents` and must not carry a `clin_id`. A payload that does not match its contract's type is rejected with `ERR_INVOICE_SHAPE_MISMATCH`. The `invoiced_qty` and `allowable_cost_cents`, where present, must each be zero or greater. A new invoice is born in `SUBMITTED` status; submitting it increments the contract's `version`, and on creation the system computes the invoice's `amount_cents` and `fee_portion_cents`.

The **invoice amount** depends on the contract type. For a firm-fixed-price invoice, the `amount_cents` is the referenced CLIN's `unit_price_cents` multiplied by the invoice's `invoiced_qty`, and the `fee_portion_cents` is 0. For a cost-plus invoice, the fee is computed on the already-summed allowable cost and rounded exactly once: the `fee_portion_cents` is the contract's `fixed_fee_cents` multiplied by the ratio of the invoice's `allowable_cost_cents` to the contract's `total_estimated_cost_cents`, rounded half-up to a whole cent; the `amount_cents` is then the invoice's `allowable_cost_cents` plus that `fee_portion_cents`. The rounding order is binding: compute the fee on the summed allowable cost and round it once — do not round a per-line fee and then sum, because the two approaches diverge by a cent on some inputs (for example, a fee ratio of one-fifteenth applied across three separate one-dollar lines yields 20 cents the sum-then-round way but 21 cents the round-then-sum way).

A `ContractingOfficer` approves or rejects a submitted invoice. Rejection drives `SUBMITTED` to `REJECTED` and increments the invoice's `version`. Approval drives `SUBMITTED` to `APPROVED` and is the system's principal fiscal gate. Approval is permitted only when the parent contract's `lifecycle_status` is `ACTIVE`, the parent award's status is `AWARDED` (not `PROTESTED` or `VACATED`), and two fiscal limits both hold. For a firm-fixed-price invoice, the CLIN's current `delivered_qty` plus the invoice's `invoiced_qty` must not exceed the CLIN's `funded_qty`; an approval that would over-deliver the CLIN is rejected with `ERR_CLIN_OVERDELIVERY`. For every invoice, the contract's `cumulative_invoiced_cents` plus this invoice's `amount_cents` must not exceed the contract's `obligated_amount_cents`; an approval that would breach the ceiling is rejected with `ERR_CEILING_EXCEEDED`. On a successful approval, the system sets `status` to `APPROVED`, recomputes the contract's `cumulative_invoiced_cents`, adds the `invoiced_qty` to the CLIN's `delivered_qty` for firm-fixed-price work, flips the funding posture to `CEILING_REACHED` when cumulative invoiced has exactly reached the obligated amount, and increments both the invoice's and the contract's `version`.

The **cumulative invoiced amount** is the sum of `amount_cents` over the contract's invoices whose status is `APPROVED`; submitted and rejected invoices contribute nothing. While cumulative invoiced is below the obligated amount the funding posture stays `WITHIN_CEILING`; the moment cumulative invoiced equals the obligated amount the posture becomes `CEILING_REACHED`, which blocks further option exercises.

Modifications adjust a contract's funding and option years. A `ContractingOfficer` proposes a modification, naming its `contract_id`, its `mod_type`, and the relevant amounts. The `mod_type` is `FUNDING`, `OPTION_EXERCISE`, or `ADMINISTRATIVE`. The `delta_cents` is the funding change for funding and option-exercise modifications, positive to add obligation and defaulting to 0 (and 0 for administrative modifications). The `option_value_cents` is the option-period value added when the modification is an option exercise, defaulting to 0 and ignored otherwise. The `option_window_close_at` is the latest instant an option exercise may be approved, defaulting to `null`. A new modification is born in `PROPOSED` status. Approving a modification drives `PROPOSED` to `APPROVED` and is permitted only when the parent contract's `lifecycle_status` is `ACTIVE` and the parent award's status is `AWARDED`; for an option-exercise modification, it is additionally permitted only when the contract's funding posture is `WITHIN_CEILING` and the current logical clock is at or before the `option_window_close_at`. An option exercise approved while the contract has reached its ceiling is rejected with `ERR_CEILING_REACHED_NO_OPTION`; an option exercise approved after its window has closed is rejected with `ERR_OPTION_WINDOW_CLOSED`. On approval the system recomputes the contract's `obligated_amount_cents` and increments both the modification's and the contract's `version`. Rejecting a modification drives `PROPOSED` to `REJECTED` and increments only the modification's `version`.

The **obligated amount** is recomputed from the contract's funding history: it is the contract's `base_value_cents`, plus the sum of `option_value_cents` over the contract's approved option-exercise modifications, plus the sum of `delta_cents` over the contract's approved funding modifications. Administrative modifications contribute nothing to the obligation. With no approved modifications the obligated amount equals the base value; each approved funding or option-exercise modification raises the ceiling and so widens the room available for subsequent invoice approvals.

A contract is wound down by the contracting officer. Completing a contract drives `ACTIVE` to `COMPLETE` and is permitted only when no invoice remains in `SUBMITTED` status and the parent award is still `AWARDED` (not `PROTESTED` or `VACATED`); it increments the contract's `version`. Closing out a contract drives `COMPLETE` to `CLOSED` and is permitted only when at least one CPARS report exists for the contract and the parent award is `AWARDED`; on closeout the system recomputes the awardee vendor's performance index and increments the contract's `version`. `CLOSED` and `TERMINATED` are the terminal lifecycle states; a contract reaches `TERMINATED` only through the protest cascade of §3.6.

### 3.6. Protests and the Sustained-Protest Compensation Cascade

A `Vendor` may protest an award. Filing a protest names the `award_id` protested, the `protester_vendor_id`, and the `grounds`. The protester must be a non-winning offeror of the protested award's solicitation — that is, a proposal with that vendor's id must exist for the solicitation and must not be the solicitation's `winning_proposal_id`; a protester who is not such an offeror is rejected with `ERR_PROTESTER_NOT_OFFEROR`. A new protest is born in `FILED` status, and filing it drives the parent award from `AWARDED` to `PROTESTED` (this transition requires that the award's contract, if any, is still `ACTIVE`), incrementing the award's `version`.

The contracting officer begins review of a filed protest, driving `FILED` to `UNDER_REVIEW`, permitted only when the parent award is in `PROTESTED` status, and incrementing the protest's `version`. From `UNDER_REVIEW` the officer resolves the protest by supplying an `outcome`. Resolving to `DENIED` drives the protest to `DENIED` and restores the award from `PROTESTED` back to `AWARDED`. Resolving to `SUSTAINED` drives the protest to `SUSTAINED` and vacates the award. A filed protest may instead be withdrawn by the filing vendor — withdrawal is permitted only when the acting vendor is the `protester_vendor_id` — which drives the protest to `WITHDRAWN` and restores the award to `AWARDED`. The `AWARDED`-to-`PROTESTED`-and-back dimension is cyclic; the resolve operation increments the protest's `version`, and the consequent award restoration or vacatur increments the award's `version`. `SUSTAINED`, `DENIED`, and `WITHDRAWN` are the terminal protest states.

A sustained protest triggers a deep compensation cascade that unwinds the award and everything beneath it back to the pre-award position. The award is driven to `VACATED`. The previously awarded proposal reverts from `AWARDED` to `ACCEPTABLE`, and each sibling proposal that had been cascaded to `REJECTED` reverts to `ACCEPTABLE` or `UNACCEPTABLE` according to its own merit. The solicitation's `winning_proposal_id` is cleared back to `null` and the solicitation's status reverts from `AWARDED` to `EVALUATED`. If a contract had been created for the vacated award, that contract's `lifecycle_status` is driven from `ACTIVE` to `TERMINATED` and its CLINs and invoices freeze. Every entity touched in this cascade has its `version` incremented. The exclusion of terminated contracts from later performance scoring (described in §3.7) is what keeps a vacated award from polluting the vendor's record.

### 3.7. Performance Reporting and the Vendor Performance Index

A `ContractingOfficer` files a CPARS performance report against a contract, supplying a `rating` that is one of `EXCEPTIONAL`, `VERY_GOOD`, `SATISFACTORY`, `MARGINAL`, or `UNSATISFACTORY`. The report records its `contract_id`, and on creation the system maps the rating to a `rating_value`: `EXCEPTIONAL` maps to 100, `VERY_GOOD` to 85, `SATISFACTORY` to 70, `MARGINAL` to 50, and `UNSATISFACTORY` to 0.

A vendor's **performance index** is the mean of these numeric ratings across the vendor's qualifying contracts, recomputed from scratch each time one of the vendor's contracts is closed out. The qualifying set is the vendor's contracts whose `lifecycle_status` is either `ACTIVE` or `CLOSED`; contracts that are `TERMINATED` are excluded so that a vacated award does not drag the index down, and contracts that are merely `COMPLETE` but not yet closed are likewise outside the qualifying set. Collect every CPARS report attached to those qualifying contracts. When that collection is empty, the `performance_index` is `null`. Otherwise the `performance_index` is the mean of the `rating_value` across all collected reports, rounded half-up to two decimal places.

### 3.8. Validation Ordering and Precedence

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a request missing its identity headers is rejected with `ERR_UNAUTHENTICATED` before anything else. Authorization comes second: a role not permitted for the operation is rejected with `ERR_FORBIDDEN_ROLE`. The segregation-of-duties check on award creation comes third, rejecting an award made by the evaluation chair with `ERR_SEGREGATION_OF_DUTIES` before the system looks further into the request. Existence comes fourth: every referenced resource is checked left-to-right and a missing one yields `ERR_NOT_FOUND`. State validity comes fifth: a transition requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409) on every state-transition endpoint. Only after these gates pass does the system evaluate the operation-specific business rules — proposal eligibility on award, set-aside and registration and deadline checks on submission, the option window and factor-weight and uniqueness and shape and over-delivery and ceiling checks on their respective operations.

Two general validations sit at the boundary. A semantic validation failure not covered by a more specific code — most notably a `CPFF` contract created without its required `total_estimated_cost_cents` or `fixed_fee_cents` — is rejected with `ERR_VALIDATION`. A malformed request body — a missing required field, a value outside its allowed enum, or an out-of-range number such as a `raw_score` outside 0 to 100, a `rating` not in its enum, or a `uei` that is not exactly 12 characters — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource, including every state-transition action and the logical-clock control, return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | ContractingOfficer |
| POST | `/vendors` | Create a vendor registration (DRAFT) | Vendor |
| GET | `/vendors/{id}` | Fetch one vendor registration | Vendor, ContractingOfficer, Auditor |
| GET | `/vendors` | List vendor registrations | Vendor, ContractingOfficer, Auditor |
| POST | `/vendors/{id}/activate` | Activate or revive a registration | Vendor |
| POST | `/vendors/{id}/expire` | Expire an active registration | ContractingOfficer |
| POST | `/vendors/{id}/exclude` | Debar/exclude a registration | ContractingOfficer |
| POST | `/solicitations` | Create a solicitation (DRAFT) | ContractingOfficer |
| GET | `/solicitations/{id}` | Fetch a solicitation | Vendor, ContractingOfficer, Auditor |
| GET | `/solicitations` | List solicitations | Vendor, ContractingOfficer, Auditor |
| POST | `/solicitations/{id}/factors` | Add an evaluation factor | ContractingOfficer |
| GET | `/solicitations/{id}/factors` | List evaluation factors | Vendor, ContractingOfficer, Auditor |
| POST | `/solicitations/{id}/open` | Open a solicitation | ContractingOfficer |
| POST | `/solicitations/{id}/amend` | Amend an open solicitation | ContractingOfficer |
| POST | `/solicitations/{id}/close` | Close a solicitation after the deadline | ContractingOfficer |
| POST | `/solicitations/{id}/finalize-evaluation` | Finalize evaluation; record the chair | ContractingOfficer |
| POST | `/solicitations/{id}/cancel` | Cancel a solicitation | ContractingOfficer |
| POST | `/proposals` | Create a draft proposal | Vendor |
| GET | `/proposals/{id}` | Fetch a proposal | Vendor, ContractingOfficer, Auditor |
| GET | `/proposals` | List proposals | Vendor, ContractingOfficer, Auditor |
| POST | `/proposals/{id}/scores` | Attach a factor score to a proposal | Vendor, ContractingOfficer |
| GET | `/proposals/{id}/scores` | List a proposal's factor scores | Vendor, ContractingOfficer, Auditor |
| GET | `/factor-scores/{id}` | Fetch one factor score | Vendor, ContractingOfficer, Auditor |
| GET | `/factor-scores` | List factor scores | Vendor, ContractingOfficer, Auditor |
| POST | `/proposals/{id}/submit` | Submit a proposal | Vendor |
| POST | `/proposals/{id}/begin-evaluation` | Begin or resume evaluation | ContractingOfficer |
| POST | `/proposals/{id}/score` | Score a proposal under evaluation | ContractingOfficer |
| POST | `/awards` | Make an award | ContractingOfficer |
| GET | `/awards/{id}` | Fetch an award | Vendor, ContractingOfficer, Auditor |
| GET | `/awards` | List awards | Vendor, ContractingOfficer, Auditor |
| POST | `/contracts` | Create a contract realizing an award | ContractingOfficer |
| GET | `/contracts/{id}` | Fetch a contract | Vendor, ContractingOfficer, Auditor |
| GET | `/contracts` | List contracts | Vendor, ContractingOfficer, Auditor |
| POST | `/contracts/{id}/clins` | Add a CLIN to a contract | ContractingOfficer |
| GET | `/contracts/{id}/clins` | List a contract's CLINs | Vendor, ContractingOfficer, Auditor |
| POST | `/contracts/{id}/complete` | Mark a contract complete | ContractingOfficer |
| POST | `/contracts/{id}/closeout` | Close out a contract | ContractingOfficer |
| POST | `/invoices` | Submit an invoice (WAWF) | Vendor |
| GET | `/invoices/{id}` | Fetch an invoice | Vendor, ContractingOfficer, Auditor |
| GET | `/invoices` | List invoices | Vendor, ContractingOfficer, Auditor |
| POST | `/invoices/{id}/approve` | Approve an invoice | ContractingOfficer |
| POST | `/invoices/{id}/reject` | Reject an invoice | ContractingOfficer |
| POST | `/contracts/{id}/modifications` | Propose a modification | ContractingOfficer |
| GET | `/contracts/{id}/modifications` | List a contract's modifications | Vendor, ContractingOfficer, Auditor |
| GET | `/modifications/{id}` | Fetch a modification | Vendor, ContractingOfficer, Auditor |
| POST | `/modifications/{id}/approve` | Approve a modification | ContractingOfficer |
| POST | `/modifications/{id}/reject` | Reject a modification | ContractingOfficer |
| POST | `/protests` | File a protest against an award | Vendor |
| GET | `/protests/{id}` | Fetch a protest | Vendor, ContractingOfficer, Auditor |
| GET | `/protests` | List protests | Vendor, ContractingOfficer, Auditor |
| POST | `/protests/{id}/begin-review` | Begin review of a protest | ContractingOfficer |
| POST | `/protests/{id}/resolve` | Resolve a protest (sustain or deny) | ContractingOfficer |
| POST | `/protests/{id}/withdraw` | Withdraw a filed protest | Vendor |
| POST | `/contracts/{id}/cpars` | File a CPARS performance report | ContractingOfficer |
| GET | `/contracts/{id}/cpars` | List a contract's CPARS reports | Vendor, ContractingOfficer, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROPOSAL_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SET_ASIDE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_OPTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_FACTOR_WEIGHTS_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_UEI` | 409 Conflict |
| `ERR_DUPLICATE_CLIN` | 409 Conflict |
| `ERR_INVOICE_SHAPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLIN_OVERDELIVERY` | 422 Unprocessable Entity |
| `ERR_CEILING_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CEILING_REACHED_NO_OPTION` | 422 Unprocessable Entity |
| `ERR_PROTESTER_NOT_OFFEROR` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
