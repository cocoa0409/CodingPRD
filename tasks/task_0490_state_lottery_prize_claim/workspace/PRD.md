# State Lottery Prize Claim API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the State Lottery & Prize Claim API, the system of record that a state lottery authority uses to govern the full arc of a lottery operation: from licensing the retailers and provisioning the point-of-sale terminals that sell tickets, through validating those tickets and routing winners, to adjudicating and disbursing large prizes under strict tax and identity rules, and finally reconciling retailer commissions, running second-chance drawings, and escheating unclaimed prizes to the state. The platform exists because lottery prize administration is simultaneously a compliance discipline and a ledger discipline: every dollar that moves must be auditable, every prize over a federal reporting threshold must trigger tax withholding and identity verification, and no single official may both approve and pay the same claim.

The domain is built around a small number of peer entities — drawing games, retailers, terminals, players, tickets, prize claims, second-chance drawings and their entries, commission settlements, and escheat records — connected by foreign-key references rather than deep nesting. Much of the system's subtlety lives in its branching workflows: a prize claim forks at approval time into a cash payout or an annuity payout with divergent tax and installment math; a ticket carries two independent status axes, one for validation and one for second-chance eligibility; and a retailer license can be suspended and reactivated in a revert cycle that cascades to its terminals. Because the system handles public money and personal identity, it enforces segregation of duties between officials, optimistic concurrency on the records that snapshot accrued money, and a logical clock that drives every deadline, expiry, and escheat decision deterministically rather than by wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint. The detailed business workflows that consume these principles appear in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `LicensingAdmin`, `TerminalOperator`, `ClaimsClerk`, and `LotteryOfficer`. When a role attempts an operation it is not authorized to perform, the request is rejected with `ERR_FORBIDDEN`.

The roles map to distinct operational concerns. A `LicensingAdmin` manages retailer licensing and terminal provisioning and activation. A `TerminalOperator` sells and validates tickets at the retail counter. A `ClaimsClerk` registers players, opens prize claims, and files second-chance entries. A `LotteryOfficer` is the central authority: this role adjudicates and disburses prize claims, prepares and finalizes commission settlements, runs and cancels second-chance drawings, reinstates lapsed self-exclusions, configures games, performs escheat sweeps, and drives the logical clock. The exact set of operations each role may invoke is given by the Authorized Role(s) column of the endpoint table in Section 4.

Identity in this system is operator-based rather than entity-backed. For all four roles — `LicensingAdmin`, `TerminalOperator`, `ClaimsClerk`, and `LotteryOfficer` — the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any entity's `id`. The server does, however, record specific officer identifiers where a workflow requires an audit trail: when a `LotteryOfficer` begins adjudicating a claim, that officer's `X-User-ID` is stored on the claim as `adjudicated_by_user_id`; when a claim is disbursed, the disbursing officer's `X-User-ID` is stored as `disbursed_by_user_id`; when a commission settlement is created, the preparing officer's `X-User-ID` is stored as `prepared_by_user_id`; and when a settlement is finalized, the approving officer's `X-User-ID` is stored as `approved_by_user_id`. These recorded identifiers are the basis for the segregation-of-duties checks described in Section 2.6, but they remain opaque operator strings, not references to any entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A `limit` or `offset` outside its permitted range — for example a `limit` above 100 or below 1 — is rejected with `ERR_VALIDATION_FILTER_INVALID`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List responses carry the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Identifiers, and Timestamps

Every entity in the system carries a server-minted `id` formatted as a UUID with no type prefix, together with a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. All entities in this system are mutable system-of-record objects, and so each also carries an `updated_at` timestamp (an ISO 8601 UTC instant refreshed on every change to the resource) and an integer `version` that begins at its initial value when the resource is created and increments by one on every mutation. The `version` field underpins the optimistic concurrency mechanism described in Section 2.5.

Time in this system is governed by a single logical clock, never by wall-clock time. At server startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-set call it holds precisely this default rather than falling back to the host's real time. An administrative capability lets an authorized officer move the clock to an arbitrary UTC instant by supplying a target instant as `to_iso8601`; every deadline, expiry, and window comparison in the system reads the logical clock. This makes deadline-sensitive behavior — claim windows, self-exclusion windows, second-chance entry deadlines, and escheat eligibility — fully deterministic and test-drivable.

### 2.5. Optimistic Concurrency Control on Snapshotting Operations

Two write operations in this system take a snapshot of a parent entity's accrued state at the moment they execute, and both are guarded by optimistic concurrency control so that a client cannot act on a parent it has not freshly observed.

The first is commission-settlement creation. A request to prepare a settlement must carry `expected_retailer_version`, which is a non-optional input field carrying the client's last observed `version` of the target retailer. Creating a settlement snapshots the retailer's accrued `commission_balance_cents` into the settlement's gross, clawback, and net figures, so the snapshot is only valid against the retailer the client actually read. If the retailer's `version` has advanced since the client last observed it — because another writer already created a settlement that consumed the same accrued window, or because a counter-pay accrued additional balance — then `expected_retailer_version` no longer matches the retailer's current `version`, the snapshot would be stale, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

The second is running a second-chance drawing. The run request must carry `expected_drawing_version`, a non-optional input field carrying the client's last observed `version` of the target drawing. Running the drawing selects a winner over the entry set the client last observed, so if the drawing's `version` has advanced since then — because an entry was added or the drawing was already run — the client's view of the candidate pool is stale, `expected_drawing_version` no longer matches the drawing's current `version`, and the run is rejected with `ERR_STALE_VERSION` (HTTP 412) so it cannot select a winner over an outdated entry set.

These two endpoints are the only ones that accept a version field. No other endpoint takes an `expected_<parent>_version` input, and none performs a version check.

### 2.6. Segregation of Duties

Because the system disburses public money, certain pairs of duties must be performed by different officials, and the separation is enforced on the recorded `X-User-ID` of each step rather than on roles (all the duties involved are performed by the `LotteryOfficer` role). Two separations are enforced.

For prize claims, the officer who disburses a claim must differ from the officer who adjudicated it. When a claim is disbursed, the acting `X-User-ID` is compared against the `adjudicated_by_user_id` recorded at adjudication; if they are the same identifier, the disbursement is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). The approval step, by contrast, must be performed by the same officer who began adjudication: approval and rejection both require the acting `X-User-ID` to equal `adjudicated_by_user_id`.

For commission settlements, the officer who approves (finalizes) a settlement must differ from the officer who prepared it. When a settlement is finalized, the acting `X-User-ID` is compared against the `prepared_by_user_id` recorded at preparation; if they match, the finalization is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts in the system are stored and exchanged as integer cents — there are no fractional-cent values. Wherever a monetary amount is produced by multiplying a base figure by a rate (a tax rate, a commission rate, a cashing-bonus rate, a cash-option factor), the product is rounded to the nearest whole cent using round-half-up, and that rounding is applied at the point of each multiplication before any summation, exactly as specified for each calculation in Section 3. Where a calculation divides an amount across installments, the division uses floor (integer division that drops any remainder), as described for annuity installments. The precise evaluation order — which multiplications round first and whether a sum is rounded once or per term — differs between calculations and is stated explicitly in the relevant Section 3 narrative; implementers must follow the stated order rather than assume a uniform one.

### 2.8. Cascading State Changes and Hierarchical Consistency

Several operations mutate more than one entity. When a parent transition triggers changes to its children, each affected child is mutated independently — its `status` (or `validation_status` / `second_chance_status`, as applicable) is updated, its `updated_at` is refreshed, and its `version` is incremented — and the parent itself likewise refreshes `updated_at` and increments `version`. The specific cascades are detailed where the triggering workflow is described in Section 3: suspending or revoking a retailer license deactivates its terminals; rejecting or voiding a prize claim returns its ticket to a claimable state; running or cancelling a second-chance drawing propagates outcomes to every entry and its ticket; finalizing a settlement moves the retailer's ledger; and the escheat sweep transitions expired winning tickets and creates escheat records. A cascaded transition is as authoritative as a directly requested one and increments the affected resource's `version` in the same way.

### 2.9. Resource Existence and Reference Resolution

Every resource referenced by a request — whether by a path identifier or by a foreign-key field in the request body — must exist. References are resolved left to right in the order they appear, and the first reference that cannot be resolved causes the request to be rejected with `ERR_NOT_FOUND` before any later reference or business rule is evaluated. This applies to path identifiers (for example the `{id}` of a ticket, claim, drawing, or settlement) and to body foreign keys alike (for example a `retailer_id` on a terminal, a `game_id` and `terminal_id` on a ticket, or a `ticket_id` and `player_id` on a prize claim). Because entity relationships in this system are expressed as flat foreign-key references rather than nested URL paths, list endpoints support reverse lookup by foreign key through query filters, described alongside each workflow.

### 2.10. Uniqueness Constraints

Four fields must be unique across their entity type. A retailer's `tax_id` is unique across retailers; a terminal's `serial_number` is unique across terminals; a ticket's `serial` is unique across tickets; and a player's `government_id_number` is unique across players. An attempt to create a record that would duplicate any of these is rejected with `ERR_DUPLICATE_RESOURCE`.

### 2.11. Request Validation and Rule Ordering

Beyond the structural checks above, every create and update validates that required fields are present and that each value has the correct type and falls within its allowed enum or numeric range; a malformed body is rejected with `ERR_INVALID_REQUEST`. When several checks could apply to one request, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after those structural gates does the system evaluate the optimistic-concurrency version check (`ERR_STALE_VERSION`), followed by the business-safety rules — self-exclusion at adjudication (`ERR_PLAYER_SELF_EXCLUDED`) and the two segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`) — and then the remaining domain constraints (annuity eligibility, identity verification, claim-window expiry, second-chance eligibility and closure, retailer licensing, terminal activity, uniqueness, body validation, and ticket claimability) described where their workflows appear. The practical effect is that, for instance, a request against a resource in the wrong state surfaces `ERR_INVALID_STATE` rather than a later business-rule error, and an over-threshold structural failure is never masked by a deeper domain check.

## 3. Business Logic & Workflows

### 3.1. Game Configuration

Everything in the system hangs off a **drawing game**. A `LotteryOfficer` configures a game by supplying its `name`, its `game_type` — one of `JACKPOT`, `INSTANT`, or `DAILY` — and the `claim_window_days`, an integer of at least 1 giving how many days after a ticket's draw a winning ticket remains claimable before it may escheat. The officer may also supply the game's tax and payout parameters; each has a default when omitted. The `federal_withholding_threshold_cents` is the gross prize amount, in cents, at or above which federal withholding applies and a claim must be handled centrally as an over-threshold claim rather than paid at the counter; it defaults to 60000000 (six hundred thousand dollars) and must be a non-negative integer. The `federal_withholding_rate` is the federal withholding fraction applied when the threshold is met, defaulting to 0.24 and constrained to be at least 0 and strictly below 1; the `state_withholding_rate` is the corresponding state fraction, defaulting to 0.05 under the same bounds. For jackpot games, the `cash_option_factor` is the multiplier that converts an advertised annuity prize into its lump-sum cash value; it defaults to 0.60 and must be greater than 0 and at most 1. The `annuity_years` is the number of annual installments a jackpot annuity is split across; it defaults to 30 and must be an integer of at least 1. A game is created already in `ACTIVE` `status` (the only value the game lifecycle takes in this version), set by system initialization with no separate activation step. Any official may read a game by its `id` or list games, optionally filtering by `status`.

### 3.2. Retailer Licensing and the Suspension Cycle

A `LicensingAdmin` registers a **retailer** by supplying its `business_name` and `tax_id`, and may optionally set the retailer's `commission_rate` (the fraction of gross sales earned as commission, defaulting to 0.06 and bounded at least 0 and below 1) and its `cashing_bonus_rate` (the fraction of a counter-paid prize the retailer earns as a cashing bonus, defaulting to 0.01 under the same bounds). A new retailer begins with `license_status` `PENDING`. Two computed ledger fields track money over the retailer's life: `commission_balance_cents`, the live balance of cashing bonuses accrued at the counter but not yet reversed or settled, which begins at 0 and is never allowed to go negative; and `lifetime_settled_cents`, the cumulative commission ever paid out across all finalized settlements, which also begins at 0. A read of a retailer returns both computed fields.

The license follows a deliberate lifecycle. Activating a `PENDING` retailer transitions `license_status` from `PENDING` to `ACTIVE`. An `ACTIVE` license may be suspended, transitioning `license_status` `ACTIVE → SUSPENDED`; this is the gate behind the retailer's ability to sell and validate tickets. Suspension is a cascade: every terminal owned by that retailer whose `status` is `ACTIVE` is transitioned `ACTIVE → DEACTIVATED`, while terminals still in `PROVISIONED` and terminals already `DEACTIVATED` are left untouched. A `SUSPENDED` license may be reactivated, transitioning `license_status` `SUSPENDED → ACTIVE` — the revert cycle — but reactivation does **not** automatically restore the terminals that were deactivated during suspension; each such terminal must be activated again explicitly. Finally, a `SUSPENDED` license may be revoked, transitioning `license_status` `SUSPENDED → REVOKED`, which is terminal; revocation cascades to deactivate every terminal of that retailer whose `status` is either `PROVISIONED` or `ACTIVE`. Activation, suspension, and revocation are each permitted only from the stated originating `license_status`; an attempt from any other state is rejected with `ERR_INVALID_STATE`. All of these license operations are performed by a `LicensingAdmin`, and each increments the retailer's `version`. Retailers may be listed with an optional `license_status` filter.

### 3.3. Terminal Provisioning and Activation

A `LicensingAdmin` provisions a **terminal** against a retailer by supplying the owning `retailer_id` and the terminal's `serial_number`. A new terminal begins with `status` `PROVISIONED`, and the system tracks `tickets_sold_count`, a computed count of tickets sold through that terminal that starts at 0. Activating a terminal transitions its `status` `PROVISIONED → ACTIVE`, but only when the owning retailer's `license_status` is `ACTIVE`; if the retailer is not currently licensed, the activation is rejected with `ERR_RETAILER_NOT_LICENSED`. An `ACTIVE` terminal may be explicitly deactivated, transitioning `status` `ACTIVE → DEACTIVATED`. Beyond explicit deactivation, terminals also reach `DEACTIVATED` through the retailer-license cascades of Section 3.2: an `ACTIVE` terminal is deactivated when its retailer is suspended or revoked, and a `PROVISIONED` terminal is deactivated when its retailer is revoked. `DEACTIVATED` is terminal for a terminal. Each transition increments the terminal's `version`. Terminals may be listed and filtered by `retailer_id` and by `status`.

### 3.4. Selling and Validating Tickets

A `TerminalOperator` sells a **ticket** through a terminal by supplying the `game_id` of the game it belongs to, the `terminal_id` of the selling terminal, a unique `serial`, the `price_cents` paid (an integer of at least 1), the `draw_date` (the UTC instant the ticket's draw occurred), the `declared_tier` the holder asserts, and the advertised `gross_prize_cents` for that tier. The `declared_tier` is an integer from 0 to 9 where 0 means a non-winner and 1 through 9 are winning tiers with 1 being the jackpot tier; `gross_prize_cents` is a non-negative integer and is 0 when `declared_tier` is 0. A sale is only permitted through a terminal whose `status` is `ACTIVE`; a sale through a terminal that is not active is rejected with `ERR_TERMINAL_NOT_ACTIVE`, and because a terminal can only be `ACTIVE` while its retailer is licensed, the licensing chain is enforced here as well (`ERR_RETAILER_NOT_LICENSED`). A new ticket begins with `validation_status` `UNVALIDATED` and `second_chance_status` `INELIGIBLE` — two independent status axes — and the system records its `claim_deadline` and increments the selling terminal's `tickets_sold_count`. The `claim_deadline` is computed as the `draw_date` plus exactly `claim_window_days` whole days (twenty-four hours per day), and it is also surfaced on every read of the ticket. Tickets may be listed and filtered by `game_id`, by `terminal_id`, by `validation_status`, and by `second_chance_status`.

Validation is the branching heart of the ticket lifecycle, and a single validate action by a `TerminalOperator` routes an `UNVALIDATED` ticket to one of four outcomes based on its declared tier, its prize amount relative to the game's federal threshold, and the claim deadline. In every branch the selling terminal must currently be `ACTIVE`, or the validate is rejected with `ERR_TERMINAL_NOT_ACTIVE`.

- **Non-winner.** When the `declared_tier` is 0, the ticket transitions `UNVALIDATED → VALIDATED_NONWINNER`, and at the same time its `second_chance_status` is set from `INELIGIBLE` to `ELIGIBLE`, because a non-winning ticket becomes eligible to be entered into a second-chance drawing.
- **Over-threshold winner.** When the `declared_tier` is between 1 and 9 and the `gross_prize_cents` is at or above the game's `federal_withholding_threshold_cents`, the prize is too large to pay at the counter and must be claimed centrally: the ticket transitions `UNVALIDATED → VALIDATED_WINNER`, and its `second_chance_status` remains `INELIGIBLE` because winning tickets never enter second chance. This branch requires that the logical clock not have passed the ticket's `claim_deadline`; if the deadline has strictly passed, the validate is rejected with `ERR_CLAIM_WINDOW_EXPIRED`.
- **Counter-paid winner.** When the `declared_tier` is between 1 and 9 but the `gross_prize_cents` is strictly below the federal threshold, the prize is small enough to pay at the counter immediately: the ticket transitions `UNVALIDATED → PAID_AT_COUNTER`. Paying at the counter accrues a cashing bonus to the retailer that owns the selling terminal — see Section 3.8 for the bonus math and ledger effect. This branch likewise requires that the logical clock not have passed the `claim_deadline`, failing with `ERR_CLAIM_WINDOW_EXPIRED` otherwise.
- **Expired.** When the ticket is still `UNVALIDATED` and the logical clock is strictly past the ticket's `claim_deadline`, validation transitions the ticket `UNVALIDATED → REJECTED`; an expired ticket cannot be validated into any active state. `REJECTED` is terminal.

A ticket may only be validated while it is `UNVALIDATED`; an attempt to validate a ticket in any other validation state is rejected with `ERR_INVALID_STATE`. Each validation increments the ticket's `version`.

### 3.5. Opening, Adjudicating, and Disbursing Prize Claims

Over-threshold prizes are settled through a **prize claim**. A `ClaimsClerk` opens a claim by supplying the `ticket_id` of the winning ticket, the `player_id` of the claimant, and the claimant's elected `payout_option`, which is either `CASH` or `ANNUITY`. A claim may only be opened against a ticket whose `validation_status` is `VALIDATED_WINNER`; a claim against a ticket in any other state is rejected with `ERR_TICKET_NOT_CLAIMABLE`. Because these are over-threshold prizes, the claimant must have a non-empty `government_id_number` on file; a claim whose linked player lacks an identity number is rejected with `ERR_ID_VERIFICATION_REQUIRED`. If the elected option is `ANNUITY`, the ticket's game must be of `game_type` `JACKPOT`; an annuity election on a non-jackpot game is rejected with `ERR_ANNUITY_NOT_ALLOWED`. The claim also fails with `ERR_CLAIM_WINDOW_EXPIRED` if the logical clock has strictly passed the ticket's `claim_deadline`. On success the claim is created in `status` `SUBMITTED`, and as a cascade the ticket's `validation_status` moves `VALIDATED_WINNER → CLAIM_PENDING`, taking it out of circulation while the claim is open. Claims may be read by `id`, listed, and filtered by `ticket_id`, by `player_id`, and by `status`. A claim read returns all of its computed money fields.

A `LotteryOfficer` begins adjudication, moving the claim `SUBMITTED → ADJUDICATING` and recording that officer's `X-User-ID` as `adjudicated_by_user_id`. Adjudication cannot begin if the claimant is under an active self-exclusion (see Section 3.6); such a claim is rejected with `ERR_PLAYER_SELF_EXCLUDED`. From `ADJUDICATING`, the same adjudicating officer resolves the claim. Approval forks on the elected `payout_option`: a `CASH` claim moves `ADJUDICATING → APPROVED_CASH` and an `ANNUITY` claim moves `ADJUDICATING → APPROVED_ANNUITY` (and, again, an annuity approval requires the game to be `JACKPOT`, else `ERR_ANNUITY_NOT_ALLOWED`). In both approval branches the system computes the claim's money fields by the payout calculation of Section 3.7; the difference is only that the cash branch leaves `annual_installment_cents` at 0 while the annuity branch populates it. Alternatively the officer may reject the claim, moving it `ADJUDICATING → REJECTED`; rejection cascades the ticket `CLAIM_PENDING → VALIDATED_WINNER` so the prize becomes claimable again. Beginning adjudication, approving, and rejecting each require the acting `X-User-ID` to equal the claim's `adjudicated_by_user_id` (for the approve and reject steps) — only the officer who took the claim into adjudication may resolve it.

Disbursement is the terminal money movement. A `LotteryOfficer` disburses an approved claim, moving it `APPROVED_CASH → PAID` or `APPROVED_ANNUITY → PAID` and recording that officer's `X-User-ID` as `disbursed_by_user_id`. By segregation of duties, the disbursing `X-User-ID` must differ from the claim's `adjudicated_by_user_id`; if they are the same, disbursement is rejected with `ERR_SEGREGATION_OF_DUTIES`. After a claim is paid, its ticket remains `CLAIM_PENDING` permanently: a paid prize's ticket is neither re-claimable nor escheatable. A claim still in `SUBMITTED` — that is, before adjudication has begun — may instead be voided, moving it `SUBMITTED → VOIDED` and cascading the ticket `CLAIM_PENDING → VALIDATED_WINNER` to return it to circulation. `PAID`, `REJECTED`, and `VOIDED` are the terminal states of a claim, and every claim transition increments the claim's `version`. Any transition attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.6. Responsible Gaming and Self-Exclusion

A player is registered by a `ClaimsClerk` with a `full_name` and a `government_id_number`, the latter unique across players and required for any over-threshold claim. A new player begins with `self_exclusion_status` `NONE` and a null `exclusion_until`. A player may enroll in self-exclusion by supplying `exclusion_days` (at least 1); enrollment sets `self_exclusion_status` to `EXCLUDED` and computes `exclusion_until` as the current logical clock plus that many days (twenty-four hours each). The exclusion window is half-open and end-exclusive: a player is treated as actively excluded for guard purposes precisely while `self_exclusion_status` is `EXCLUDED` and the logical clock is strictly before `exclusion_until`. This is the condition that blocks a claim from entering adjudication in Section 3.5, surfacing as `ERR_PLAYER_SELF_EXCLUDED`.

Once the logical clock reaches or passes `exclusion_until`, the active exclusion has lapsed and the player may be reinstated. Reinstatement, performed by a `LotteryOfficer`, moves `self_exclusion_status` `EXCLUDED → REINSTATED` and clears `exclusion_until` back to null. Reinstatement is only permitted after the exclusion has lapsed; an attempt to reinstate while the exclusion is still active — that is, while the logical clock is strictly before `exclusion_until` — is rejected with `ERR_REINSTATE_TOO_EARLY`. Enrolling a player in self-exclusion may be performed by a `ClaimsClerk` or a `LotteryOfficer`; reinstatement is reserved to a `LotteryOfficer`. A player may be read by `id`.

### 3.7. Computing Payout, Withholding, and Annuity Installments

The payout calculation runs exactly once per claim, at the moment of approval, over that single claim together with its linked ticket and the ticket's game; it never aggregates across rows. Let the ticket's advertised `gross_prize_cents` be the basis figure, and read the game's `cash_option_factor`, `annuity_years`, `federal_withholding_threshold_cents`, `federal_withholding_rate`, and `state_withholding_rate`.

The first step fixes the taxable basis, `gross_payout_cents`. For a `CASH` claim on a non-jackpot game, the basis is exactly the advertised `gross_prize_cents` — the cash-option factor is never applied. For a `CASH` claim on a `JACKPOT` game, the basis is the advertised `gross_prize_cents` multiplied by the game's `cash_option_factor`, rounded half-up to the nearest cent — this is the discounted lump-sum cash value. For an `ANNUITY` claim (which is only ever a jackpot game), the basis is the full advertised `gross_prize_cents` with the cash-option factor **not** applied.

The second step computes withholding, and the threshold gate is evaluated on the **advertised** `gross_prize_cents`, not on the possibly-discounted basis. When the advertised `gross_prize_cents` is at or above the game's `federal_withholding_threshold_cents`, the `federal_withholding_cents` is `gross_payout_cents` multiplied by the `federal_withholding_rate`, rounded half-up to the nearest cent, and the `state_withholding_cents` is `gross_payout_cents` multiplied by the `state_withholding_rate`, rounded half-up to the nearest cent. When the advertised `gross_prize_cents` is below the federal threshold, both `federal_withholding_cents` and `state_withholding_cents` are 0. (In practice every claim handled through this workflow is over-threshold, but the gate is specified on the advertised amount regardless.)

The third step computes the net, and the rounding order is pinned: each withholding component is rounded individually on the full `gross_payout_cents` as just described, the two rounded withholdings are summed, and that single total is subtracted once from `gross_payout_cents` to give `net_payout_cents`. Do not subtract a withholding before the other is computed, and do not round the net separately.

The fourth step applies only to `ANNUITY` claims: the `annual_installment_cents` is the `net_payout_cents` divided by the game's `annuity_years` using floor division — any remainder is dropped from the stored per-year figure (the remainder is not redistributed into the stored installment). For a `CASH` claim, `annual_installment_cents` stays 0. Worked through, an annuity jackpot claim therefore takes the full advertised prize as its basis, withholds federal and state amounts on that full basis, nets them out once, and then floors the net across the configured number of years; a cash jackpot claim discounts the basis by the cash-option factor first and withholds on the discounted figure; and a cash non-jackpot claim withholds on the undiscounted advertised prize.

### 3.8. Retailer Commissions, Counter-Pay Bonuses, and Settlement

Retailer earnings flow from two sources that both touch the live `commission_balance_cents` ledger. The first is the cashing bonus paid when a `TerminalOperator` validates an under-threshold winner into `PAID_AT_COUNTER`. At that moment the retailer that owns the selling terminal is credited a bonus equal to the ticket's `gross_prize_cents` multiplied by the retailer's `cashing_bonus_rate`, rounded half-up to the nearest cent, and that amount is added to `commission_balance_cents`. If a `LotteryOfficer` later reverses an erroneous or expired counter-pay — moving the ticket `PAID_AT_COUNTER → COUNTER_REVERSED` — the exact same bonus amount (the ticket's `gross_prize_cents` times the retailer's `cashing_bonus_rate`, rounded half-up) is debited back out of `commission_balance_cents`, with the balance floored at 0 so it never goes negative. The reversal increments the ticket's `version`.

The second source is periodic settlement. A `LotteryOfficer` prepares a **commission settlement** for a retailer over a window by supplying the `retailer_id`, the window's `period_start` (inclusive) and `period_end` (exclusive), and the `expected_retailer_version` for the optimistic-concurrency check of Section 2.5. Preparation snapshots the window and creates the settlement in `status` `DRAFT`, recording the preparing officer as `prepared_by_user_id` and incrementing the retailer's `version`. The window is the half-open interval from `period_start` up to but not including `period_end`, and the source rows are all tickets sold by terminals that this retailer owns whose `created_at` falls within that interval.

The settlement's `gross_commission_cents` is the sum of two halves computed with deliberately different rounding orders. The sales-commission half takes **every** ticket in the window regardless of its `validation_status` — they were all sold — sums their `price_cents`, multiplies that single summed base by the retailer's `commission_rate`, and rounds the product half-up exactly once (sum first, then round). The cashing-bonus half takes only the window tickets whose `validation_status` is `PAID_AT_COUNTER`, computes for each one its `gross_prize_cents` times the retailer's `cashing_bonus_rate` rounded half-up to the nearest cent, and sums those per-ticket rounded amounts (round first, then sum). The two halves are then added to form `gross_commission_cents`. Separately, the settlement's `clawback_cents` is the sum, over window tickets whose `validation_status` is `COUNTER_REVERSED`, of each such ticket's `gross_prize_cents` times the retailer's `cashing_bonus_rate` rounded half-up to the nearest cent — recovering bonuses that were accrued and then reversed within the window. Finally, `net_settlement_cents` is `gross_commission_cents` minus `clawback_cents`, floored at 0: a retailer is never billed a negative settlement.

A `DRAFT` settlement is resolved one of two ways. Finalizing it moves it `DRAFT → FINALIZED`, records the approving officer's `X-User-ID` as `approved_by_user_id`, and performs the ledger sync: the retailer's `commission_balance_cents` is reduced by the settlement's `net_settlement_cents` and the retailer's `lifetime_settled_cents` is increased by the same `net_settlement_cents`. The approver must differ from the preparer by segregation of duties, else `ERR_SEGREGATION_OF_DUTIES`. Alternatively a `DRAFT` settlement may be voided, moving it `DRAFT → VOIDED` with no ledger movement at all — a draft that is voided never debited the balance, so nothing is reversed. `FINALIZED` and `VOIDED` are terminal, and each settlement transition increments the settlement's `version`. Any settlement action attempted from a non-`DRAFT` state is rejected with `ERR_INVALID_STATE`. Settlements may be read by `id` and listed, filtered by `retailer_id` and by `status`.

### 3.9. Second-Chance Drawings and Entries

Non-winning tickets get a second life. A `LotteryOfficer` opens a **second-chance drawing** for a game by supplying the `game_id`, an `entry_deadline` (the UTC instant after which no further entries are accepted), and the `prize_pool_cents` cash prize awarded to the winner (an integer of at least 1). A new drawing begins in `status` `OPEN`, tracks a computed `entry_count` starting at 0, and carries a `winning_entry_id` that is null until the drawing is run. Drawings may be read by `id` and listed, filtered by `game_id`, by `winning_entry_id`, and by `status`.

A `TerminalOperator` or `ClaimsClerk` files a **second-chance entry** by supplying the `drawing_id` and the `ticket_id` of the non-winning ticket being entered. An entry is accepted only when the ticket's `second_chance_status` is `ELIGIBLE`, the drawing's `status` is `OPEN`, and the logical clock is at or before the drawing's `entry_deadline`; if any of these fails, the entry is rejected with `ERR_ENTRY_NOT_ELIGIBLE`. On success the entry is created with `outcome` `PENDING`, the system stamps `entered_at` with the current logical clock (this instant is the deterministic ordinal used later to pick the winner), the ticket's `second_chance_status` moves `ELIGIBLE → ENTERED`, and the drawing's `entry_count` is incremented. Entries may be read by `id` and listed, filtered by `drawing_id`, by `ticket_id`, and by `outcome`.

Running a drawing is reserved to a `LotteryOfficer` and is guarded by the optimistic-concurrency check on `expected_drawing_version` from Section 2.5. A run is permitted only while the drawing is `OPEN`; it further requires that the logical clock be strictly past the `entry_deadline` (a drawing cannot be drawn before its entries close, else `ERR_DRAWING_NOT_CLOSED`) and that the `entry_count` be at least 1 (an empty pool cannot be drawn, else `ERR_EMPTY_DRAWING_POOL`). When it runs, the system selects the winning entry deterministically: among the drawing's entries it picks the one with the earliest `entered_at`, breaking any tie by the entry's `created_at` ascending — never by `id`. The drawing moves `OPEN → DRAWN`, its `winning_entry_id` is set to the selected entry's `id`, and the cascade fires: the selected entry's `outcome` becomes `WON` and its ticket's `second_chance_status` moves `ENTERED → DRAWN_WINNER`, while every other entry's `outcome` becomes `LOST` and each of those tickets' `second_chance_status` moves `ENTERED → DRAWN_LOSER`.

Alternatively a `LotteryOfficer` may cancel an `OPEN` drawing, moving it `OPEN → CANCELLED`. Cancellation releases every entry back to eligibility: each entry's `outcome` stays `PENDING`, and each entered ticket's `second_chance_status` moves `ENTERED → ELIGIBLE` so it may be entered into another drawing. `DRAWN` and `CANCELLED` are terminal for a drawing, and both the run and cancel transitions increment the drawing's `version` (and the affected entries' and tickets' versions through the cascade). A run or cancel attempted from a non-`OPEN` state is rejected with `ERR_INVALID_STATE`.

### 3.10. Unclaimed Prizes and Escheat

Winning prizes that are never claimed eventually escheat to the state's unclaimed-property fund. A winning ticket becomes escheatable once the logical clock is strictly past its `claim_deadline`; at the exact deadline instant the ticket is still claimable, because the boundary is inclusive of the deadline and escheat requires a strictly-later clock. A `LotteryOfficer` triggers the escheat sweep, an administrative capability that scans every ticket whose `validation_status` is `VALIDATED_WINNER` and whose `claim_deadline` is strictly before the current logical clock, transitions each such ticket `VALIDATED_WINNER → ESCHEATED`, and for each creates an **escheat record** whose `escheated_amount_cents` equals the ticket's `gross_prize_cents` and whose `escheated_at` is the logical-clock value at sweep time. `ESCHEATED` is terminal for a ticket, and each swept ticket's `version` is incremented. The sweep reports how many tickets it escheated and the identifiers of those tickets. Only winning tickets still sitting in `VALIDATED_WINNER` are eligible; a ticket whose claim is pending or already paid (`CLAIM_PENDING`) is not swept, which is why a paid prize's ticket is never escheated. Escheat records may be read by `id` and listed, filtered by `ticket_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state transition and every administrative action — return a `200 OK` status code. The request body, response body, computed side effects, and validation rules for each endpoint are not repeated here; they are described in the Section 3 narrative for the corresponding workflow.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/games` | Create a drawing game configuration | LotteryOfficer |
| GET | `/games/{id}` | Fetch a game by id | LotteryOfficer, LicensingAdmin, ClaimsClerk, TerminalOperator |
| GET | `/games` | List games | LotteryOfficer, LicensingAdmin, ClaimsClerk, TerminalOperator |
| POST | `/retailers` | Register a retailer (starts PENDING) | LicensingAdmin |
| GET | `/retailers/{id}` | Fetch a retailer (includes computed ledger fields) | LotteryOfficer, LicensingAdmin |
| GET | `/retailers` | List retailers | LotteryOfficer, LicensingAdmin |
| POST | `/retailers/{id}/license/activate` | Activate a PENDING or SUSPENDED retailer license | LicensingAdmin |
| POST | `/retailers/{id}/license/suspend` | Suspend an ACTIVE license; cascades terminal deactivation | LicensingAdmin |
| POST | `/retailers/{id}/license/revoke` | Revoke a SUSPENDED license; cascades terminal deactivation | LicensingAdmin |
| POST | `/terminals` | Provision a terminal to a retailer (starts PROVISIONED) | LicensingAdmin |
| GET | `/terminals/{id}` | Fetch a terminal | LotteryOfficer, LicensingAdmin, TerminalOperator |
| GET | `/terminals` | List terminals; filter by retailer_id, status | LotteryOfficer, LicensingAdmin, TerminalOperator |
| POST | `/terminals/{id}/activate` | Activate a PROVISIONED terminal (requires retailer ACTIVE) | LicensingAdmin |
| POST | `/terminals/{id}/deactivate` | Deactivate an ACTIVE terminal | LicensingAdmin |
| POST | `/players` | Register a player/claimant | ClaimsClerk |
| GET | `/players/{id}` | Fetch a player | LotteryOfficer, ClaimsClerk |
| POST | `/players/{id}/self-exclude` | Enroll a player in self-exclusion | ClaimsClerk, LotteryOfficer |
| POST | `/players/{id}/reinstate` | Reinstate a player whose exclusion has lapsed | LotteryOfficer |
| POST | `/tickets` | Sell (create) a ticket via an ACTIVE terminal | TerminalOperator |
| GET | `/tickets/{id}` | Fetch a ticket (includes computed claim_deadline) | LotteryOfficer, ClaimsClerk, TerminalOperator |
| GET | `/tickets` | List tickets; filter by game_id, terminal_id, validation_status, second_chance_status | LotteryOfficer, ClaimsClerk, TerminalOperator |
| POST | `/tickets/{id}/validate` | Validate a ticket; routes by tier, threshold, and deadline | TerminalOperator |
| POST | `/tickets/{id}/reverse-counter-pay` | Reverse a counter-pay; debits the retailer's cashing bonus | LotteryOfficer |
| POST | `/prize-claims` | Open an over-threshold claim against a VALIDATED_WINNER ticket | ClaimsClerk |
| GET | `/prize-claims/{id}` | Fetch a prize claim (includes computed money fields) | LotteryOfficer, ClaimsClerk |
| GET | `/prize-claims` | List prize claims; filter by ticket_id, player_id, status | LotteryOfficer, ClaimsClerk |
| POST | `/prize-claims/{id}/begin-adjudication` | Move a SUBMITTED claim to ADJUDICATING | LotteryOfficer |
| POST | `/prize-claims/{id}/approve` | Approve an ADJUDICATING claim; forks CASH vs ANNUITY | LotteryOfficer |
| POST | `/prize-claims/{id}/reject` | Reject an ADJUDICATING claim; returns ticket to claimable | LotteryOfficer |
| POST | `/prize-claims/{id}/disburse` | Disburse an approved claim; enforces segregation of duties | LotteryOfficer |
| POST | `/prize-claims/{id}/void` | Void a SUBMITTED claim; returns ticket to claimable | LotteryOfficer |
| POST | `/second-chance-drawings` | Create a second-chance drawing for a game | LotteryOfficer |
| GET | `/second-chance-drawings/{id}` | Fetch a drawing (includes computed entry_count, winning_entry_id) | LotteryOfficer, ClaimsClerk, TerminalOperator |
| GET | `/second-chance-drawings` | List drawings; filter by game_id, winning_entry_id, status | LotteryOfficer, ClaimsClerk, TerminalOperator |
| POST | `/second-chance-drawings/{id}/run` | Run a closed drawing; selects earliest-entered winner with OCC | LotteryOfficer |
| POST | `/second-chance-drawings/{id}/cancel` | Cancel an OPEN drawing; releases entries to ELIGIBLE | LotteryOfficer |
| POST | `/second-chance-entries` | Enter an ELIGIBLE non-winning ticket into an OPEN drawing | TerminalOperator, ClaimsClerk |
| GET | `/second-chance-entries/{id}` | Fetch a single entry | LotteryOfficer, ClaimsClerk, TerminalOperator |
| GET | `/second-chance-entries` | List entries; filter by drawing_id, ticket_id, outcome | LotteryOfficer, ClaimsClerk, TerminalOperator |
| POST | `/commission-settlements` | Prepare (snapshot) a settlement for a retailer window; OCC on the retailer | LotteryOfficer |
| GET | `/commission-settlements/{id}` | Fetch a settlement (includes computed gross/clawback/net) | LotteryOfficer |
| GET | `/commission-settlements` | List settlements; filter by retailer_id, status | LotteryOfficer |
| POST | `/commission-settlements/{id}/finalize` | Finalize a DRAFT settlement; segregation of duties; debits ledger | LotteryOfficer |
| POST | `/commission-settlements/{id}/void` | Void a DRAFT settlement (no ledger movement) | LotteryOfficer |
| GET | `/escheat-records/{id}` | Fetch an escheat record | LotteryOfficer |
| GET | `/escheat-records` | List escheat records; filter by ticket_id | LotteryOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a UTC instant | LotteryOfficer, LicensingAdmin |
| POST | `/_clock/run_escheat_sweep` | Run the unclaimed-prize escheat sweep | LotteryOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PLAYER_SELF_EXCLUDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_ANNUITY_NOT_ALLOWED` | 422 |
| `ERR_ID_VERIFICATION_REQUIRED` | 422 |
| `ERR_CLAIM_WINDOW_EXPIRED` | 409 |
| `ERR_ENTRY_NOT_ELIGIBLE` | 409 |
| `ERR_DRAWING_NOT_CLOSED` | 409 |
| `ERR_EMPTY_DRAWING_POOL` | 409 |
| `ERR_RETAILER_NOT_LICENSED` | 409 |
| `ERR_TERMINAL_NOT_ACTIVE` | 409 |
| `ERR_TICKET_NOT_CLAIMABLE` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_REINSTATE_TOO_EARLY` | 409 |
| `ERR_VALIDATION_FILTER_INVALID` | 422 |
