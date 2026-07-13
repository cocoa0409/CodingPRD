# Consumer DNA Genealogy API — Product Requirements Document

## 1. Introduction

Consumer genetic-testing platforms sit at an uncomfortable intersection. On one side is a physical logistics and laboratory operation: cardboard kits shipped to households, saliva swabs returned to a sequencing facility, extraction chemistry that fails often enough to need retries, and genotyping instruments that can only read the chip they were built for. On the other side is the most sensitive category of personal data a consumer will ever hand over — a genome that implicates not just the customer but every biological relative they have never met. The API described here governs both halves and, critically, the coupling between them.

The system tracks a customer from the moment an operator registers their account, through the ordering and barcode activation of a test kit, the laboratory pipeline that turns a swab into a set of genotype markers, and the generation of consent-gated ancestry and health reports. It then extends outward: DNA-relative matching pairs customers against one another, record hints propagate matched relatives into user-built family trees, and a subscription tier decides how much of that surface a customer may actually reach. Every one of these capabilities is conditioned on a consent grant that the customer may withdraw at any moment, and a withdrawal is not a flag flip — it propagates through matches, through the counterpart's visible relative count, and through hints already sitting in someone else's tree.

The design goal is auditability under withdrawal. A privacy regime that only works when nobody exercises their rights is not a privacy regime. Accordingly, this specification is unusually explicit about cascades, compensating actions, conserved ledger quantities, and the exact instant at which a deferred deletion becomes irreversible. Implementers should read the cascade descriptions in Section 3 as normative rather than illustrative: the secondary and tertiary effects of an operation are as much a part of its contract as its primary state transition. The entire API is mounted under the `/dna` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. If either header is absent, or if `X-User-Role` is not one of the four recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The four roles are `Customer`, `LabTechnician`, `PrivacyOfficer`, and `PlatformAdmin`. When the headers are well-formed but the acting role is not among the roles authorized for the requested endpoint (see the table in Section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a Customer compare the resource's owning-customer field to `X-User-ID`. A `Customer` may only act on their own subscriptions, kits, consent grants, reports, relative matches, family trees, tree people, record hints, and data requests. Reaching for a resource that belongs to a different Customer yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Ownership of a resource that is not directly stamped with a customer identifier is resolved by walking up the chain — a tree person belongs to the customer who owns its family tree, and a record hint belongs to the customer who owns the tree of the person it is attached to.

The three operator roles carry opaque identities. When `X-User-Role` is `LabTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same is true when `X-User-Role` is `PlatformAdmin`. When `X-User-Role` is `PrivacyOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, but the server does record it: the officer who decides a privacy request has their `X-User-ID` written verbatim into that request's `reviewed_by` field. It is never compared against any Customer's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, may not be lower than 1, and may not exceed 100. `offset` is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. `total_count` reflects the size of the filtered result set before pagination is applied, and `has_more` is true exactly when items remain beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource in this system — customers, subscriptions, kits, samples, lab instruments, lab batches, consent grants, reports, relative matches, family trees, tree people, record hints, and data requests — carries the same four system-managed properties:

- `id` (string): a server-minted UUID. It never carries a type prefix, and clients must never construct one.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource first came into being.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource, including mutations that the server performs on its own initiative as part of a cascade.
- `version` (integer): a counter that begins at 1 on creation and increments by exactly 1 on every mutation. It is the handle clients use for optimistic concurrency control.

There is a subtlety worth stating plainly, because cascade correctness depends on it: when a cascade reaches a resource the client never named — the counterpart customer in a relative match, the kit behind a failed sample, the tree person a withdrawn hint hung from — that resource is mutated too, and its `updated_at` and `version` move accordingly.

Time in this system is not wall-clock time. The server maintains a **logical clock** which begins at the fixed instant `2026-05-01T00:00:00Z` when the process starts and only ever moves when an operator explicitly sets it, supplying the target instant as `to_iso8601`; the operation echoes the new value back as `current_utc`. It never falls back to real time. Every deadline, every window boundary, every expiry, and every timestamp written by the server reads this clock. Setting the clock mutates no entity and fires no scheduled action implicitly — deferred work executes only when its own operation is invoked.

### 2.5. Left-to-Right Resolution of Identifiers

Paths that name a resource are resolved before anything else is considered. When a path carries more than one identifier, they are validated in strict left-to-right order and the first one that fails to resolve determines the error — so a request naming a nonexistent customer never reaches the point of looking for the nested resource beneath it. The not-found codes are entity-specific: `ERR_CUSTOMER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_TREE_NOT_FOUND`, `ERR_PERSON_NOT_FOUND`, `ERR_HINT_NOT_FOUND`, and `ERR_DATA_REQUEST_NOT_FOUND`, each returned with HTTP 404.

The same discipline extends to identifiers carried inside a request payload. Any referenced entity named in the body of a create operation — the subject of a subscription, kit, consent grant, family tree, or data request; the instrument of a batch; each sample enumerated for a batch; the tree a person joins; the parent links of a person; the customer a tree person is linked to — must resolve to an existing record before business rules are evaluated. Payload-reference failures on subscription creation, kit ordering, batch creation, consent granting, tree creation, tree-person creation, and data-request filing surface the same 404 family of codes.

### 2.6. Validation Precedence

Several checks can plausibly fail on the same request, and the code returned must be deterministic. Checks are evaluated in the following order, and the first failure short-circuits the request:

1. Header presence and role recognition (`ERR_UNAUTHENTICATED`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Existence of every identifier in the path, left to right (the 404 family).
4. Existence of every referenced identifier in the request body (the 404 family).
5. Customer ownership of the target resource (`ERR_NOT_RESOURCE_OWNER`).
6. Request well-formedness — required fields present, enumerated values in range, numeric ranges respected, and uniqueness honored (`ERR_INVALID_REQUEST`).
7. The stale-version check on the two concurrency-guarded operations (`ERR_STALE_VERSION`).
8. Purged-account rejection (`ERR_CUSTOMER_PURGED`).
9. The generic state-legality check — is the transition being requested even declared out of the resource's current state (`ERR_INVALID_STATE`).
10. Then the specific business rules, in the order laid out below: barcode-already-activated, DNA readiness, extraction-attempts exhaustion, the empty-batch guard, the consent gate, sample readiness for batching, instrument availability, consent-window overlap, the consent cooling-off buffer, instrument-window overlap, barcode mismatch, tree cycle detection, the tier person limit, the one-open-privacy-request rule, subscription access lock, and finally insufficient store credit.

Well-formedness in step 6 means, concretely: a submitted DNA yield is at least 0, a submitted call rate lies between 0 and 1 inclusive, a credit adjustment amount is strictly greater than 0, a birth year is strictly greater than 0, the results submitted at batch finalize contain exactly one entry for each member sample of the batch and no others, and a customer's email address is unique across all customers. Any violation is `ERR_INVALID_REQUEST` (HTTP 400).

The ordering matters in practice. Because the stale-version check sits above the purged-account and state checks, a client holding an out-of-date view learns that fact first rather than being told the resource is in the wrong state. Because the consent gate sits below the DNA-readiness check, a customer with no genotyped sample and no consent hears about the missing DNA first.

### 2.7. Optimistic Concurrency Control

Two operations in the system can silently destroy information the client has not yet seen, and both are therefore guarded by a stale-version check.

A request to `POST /dna/customers/{id}/reports` must carry the field `expected_customer_version` in its payload, holding the `version` of the target Customer as the client last observed it. If that value does not equal the Customer's current `version` — because some other writer has advanced it since the client last read the record — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because publishing a report legitimately supersedes the customer's prior published report of the same kind; without the check, a client working from a stale view would overwrite a report it had never seen. The check forces a re-read first.

A request to `POST /dna/subscriptions/{id}/change-tier` must carry the field `expected_subscription_version` in its payload, holding the `version` of the target Subscription as the client last observed it. A mismatch with the subscription's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Here the guard protects the compensation record: a tier change overwrites `last_change_charge_cents` and `last_change_from_tier`, and a change applied on top of an unobserved change would erase the only record that makes the earlier change reversible.

No other endpoint accepts or requires a version field. Sending one elsewhere has no meaning, and the absence of a version field elsewhere is not an error.

### 2.8. Numeric Precision and Rounding

Money is handled exclusively in integer cents. There are no fractional cents anywhere in the system, and no monetary value is ever expressed as a decimal number of currency units. Where a monetary computation produces a fraction, the rounding method is specified explicitly at the point of computation in Section 3 — proration of a tier upgrade truncates downward to the whole cent, while the loyalty discount, the processing fee, and the cancellation proration all round half up to the whole cent.

Non-monetary computed quantities carry fixed precision. Shared centimorgans on a relative match are held to 2 decimal places, rounded half up. Ethnicity share percentages are held to 2 decimal places, rounded half up. A match's confidence score and a batch's pass rate are held to 4 decimal places, rounded half up; the confidence score additionally has a floor of 0.0000, meaning a computation that would land below zero is reported as zero. A hint's confidence is copied from its source match's confidence score and therefore also carries 4 decimal places.

### 2.9. Consent as a Precondition, Not a Preference

Three capabilities of this platform are gated on an explicit, time-bounded consent grant from the customer, and the gate is evaluated at the moment of the request against the logical clock — not at the moment the account was created, and not against a stored preference. Health-trait reporting requires a grant whose `scope` is `HEALTH_TRAITS`. DNA-relative matching requires a grant whose `scope` is `RELATIVE_MATCHING`. The recalibrated `FINAL` variant of an ancestry report requires a grant whose `scope` is `RESEARCH`, because the reference panel that variant recalibrates against is derived from the research cohort itself. A request that reaches for a gated capability without live consent is rejected with `ERR_CONSENT_REQUIRED` (HTTP 403).

Consent status is surfaced on the Customer record as three derived booleans. `health_opt_in` is true exactly when an `ACTIVE` grant of scope `HEALTH_TRAITS` covers the current logical-clock instant; `matching_opt_in` and `research_opt_in` are the corresponding booleans for the `RELATIVE_MATCHING` and `RESEARCH` scopes. All three default to false and are recomputed by the server whenever a grant is created or withdrawn. They are never written directly by a client.

Withdrawal is designed to be consequential. It is not enough to stop honoring a scope going forward — artifacts already produced under that scope are retracted, and matches already computed under matching consent are suppressed on both sides of the pair. The cascades are laid out in Sections 3.5 and 3.7.

### 2.10. Store Credit and Conserved Quantities

Each customer carries a store-credit balance in `wallet_credit_cents`, an integer count of cents that starts at 0 and may never go negative. Credit is debited by tier-upgrade charges and credited by three things: an operator top-up, a kit refund when the sample behind it fails terminally, and the proration refunded when a subscription is cancelled. It is also credited by the compensating action that reverts a tier change.

Two invariants govern the ledgers, and both must survive every forward operation and its compensator. The first: the sum of a customer's `wallet_credit_cents` and their subscription's `lifetime_charged_cents` is unchanged across the pair of a tier change followed by a revert of that change — whatever the charge took out of the wallet, it put into the lifetime total, and the revert moves exactly that amount back. The second: summing `visible_match_count` over every customer always yields exactly twice the number of relative matches currently in `ACTIVE` status, because every active match contributes to precisely two customers' counts. This must hold after a consent withdrawal, after a re-grant, and after a purge.

## 3. Business Logic & Workflows

### 3.1. Accounts, Subscriptions, and the Two Dimensions of Billing

An operator registers a new account by supplying an `email` and a `display_name`. The email is the login identity and must be unique across every customer; it is also, less obviously, a deterministic tie-break key that resurfaces later in relative matching and in purge ordering. A freshly registered account has `account_status` of `ACTIVE`, `dna_status` of `NO_SAMPLE`, zero store credit, zero visible matches, all three consent booleans false, and `version` of 1. The only other state `account_status` can reach is `PURGED`, which is terminal and is written by the deferred deletion machinery described in Section 3.9. The genotyping-readiness field, `dna_status`, walks `NO_SAMPLE` → `PROCESSING` → `DNA_READY` under the lab pipeline's control, can fall back to `NO_SAMPLE` when a sample dies, and lands at `PURGED` alongside the account. Operators may top up a customer's balance by supplying an `amount_cents` greater than zero; the amount is added to `wallet_credit_cents` and the customer's `version` advances by one.

A subscription is opened against a customer by naming that `customer_id` and an initial `tier`. Tiers are `FREE`, `PLUS`, and `PRO`, priced at 0, 1999, and 7999 cents per period respectively. Opening a subscription stamps `current_period_start` with the logical clock and sets `current_period_end` to exactly thirty days later — thirty days is the billing period throughout this system, and every proration in Section 3.2 divides by it. A new subscription begins with `billing_status` of `CURRENT`, `access_status` of `ACTIVE`, `lifetime_charged_cents` of zero, `pending_tier` null, `grace_until` null, `last_change_charge_cents` null, `last_change_from_tier` null, and `published_report_count` of zero.

The two status dimensions evolve **independently**, and understanding that independence is the whole of the billing model. `billing_status` takes values `CURRENT`, `PAST_DUE`, and the terminal `CLOSED`. `access_status` takes values `ACTIVE`, `GRACE`, `LOCKED`, and the terminal `CANCELLED`. An operator drives them by submitting an `event_type` of `PAYMENT_FAILED`, `PAYMENT_SUCCEEDED`, or `CANCEL`.

A `PAYMENT_FAILED` event is **routed by the current pair of dimension values**, and this routing is the single most easily-missed rule in the subscription machine:

- From the pair `CURRENT` and `ACTIVE`: the billing dimension moves `CURRENT → PAST_DUE`, and as a side effect the access dimension moves `ACTIVE → GRACE` with `grace_until` set to the logical clock plus fourteen days.
- From the pair `PAST_DUE` and `GRACE`: this is where a second failure lands. The billing dimension does **not** move — it remains `PAST_DUE`. Only the access dimension advances, `GRACE → LOCKED`, and `grace_until` is cleared back to null.
- From the pair `PAST_DUE` and `LOCKED`: there is nowhere left to go, and the event is rejected with `ERR_INVALID_STATE`.
- When `billing_status` is already `CLOSED`: rejected with `ERR_INVALID_STATE`.

A `PAYMENT_SUCCEEDED` event requires `billing_status` to be `PAST_DUE`, and is otherwise rejected with `ERR_INVALID_STATE`. It moves the billing dimension `PAST_DUE → CURRENT` and, as a side effect, restores the access dimension to `ACTIVE` from whichever of `GRACE` or `LOCKED` it currently holds, clearing `grace_until`.

A `CANCEL` event is accepted from any `billing_status` other than `CLOSED` (`ERR_INVALID_STATE` otherwise). It closes the billing dimension, moves the access dimension to `CANCELLED`, clears `pending_tier`, and computes a cancellation refund which is credited to the customer's `wallet_credit_cents`.

**The cancellation refund.** Begin by counting the whole days left in the period: take the difference between `current_period_end` and the current logical-clock instant, express it in seconds, divide by 86400, and truncate downward to a whole number of unused days. If that number comes out negative — the period has already elapsed — treat it as zero. The base refund is the tier's per-period fee multiplied by the unused days, divided by thirty, and rounded half up to a whole cent.

The refund then takes one of two forms depending on whether the customer actually consumed the period. Count the customer's reports that are currently in `PUBLISHED` status and whose `generated_at` falls at or after `current_period_start` and at or before the current logical-clock instant — this is the same count carried on the subscription as `published_report_count`, recomputed at cancellation time. Reports in `SUPERSEDED` or `REVOKED` status do not count. If that count is zero, the period was **clean** and the refund is the base refund exactly. If the count is one or more, the period was **consumed**: an unlock fee of 300 cents is deducted for each such published report, and the result is floored at zero — the refund is never negative and, for identical tier, period and clock inputs, is always strictly smaller than the clean-period refund would have been.

### 3.2. Changing Tier, and Undoing It

A customer changes their own tier by naming a `new_tier` and the `expected_subscription_version` described in Section 2.7. Regardless of direction, the subscription's `access_status` must be `ACTIVE` or `GRACE`; a `LOCKED` or `CANCELLED` subscription rejects the change with `ERR_SUBSCRIPTION_LOCKED` (HTTP 402). The direction of the change is decided purely by the per-period fees: if the new tier's fee is strictly greater than the current tier's fee, the change is an **upgrade**; if the new tier's fee is less than or equal to the current tier's fee, it is a **downgrade**. A same-tier request therefore counts as a downgrade.

A **downgrade** is deferred and free. The charge total is zero, `tier` itself does not move, `pending_tier` is set to the requested tier — the tier a scheduled downgrade will move to at `current_period_end` — `last_change_charge_cents` is set to 0, `last_change_from_tier` records the tier held before the request, and the subscription's `version` advances by one. No credit is debited.

An **upgrade** applies immediately and is charged. The charge is computed in a pinned order, and the order genuinely matters because a later step feeds off an earlier one without ever feeding back:

1. The **base delta** is the new tier's per-period fee minus the old tier's per-period fee, in cents.
2. The **remaining days** in the period are the difference between `current_period_end` and the current logical-clock instant, expressed in seconds, divided by 86400, and truncated downward to a whole number.
3. The **prorated subtotal** is the base delta multiplied by the remaining days, divided by thirty, and truncated downward to a whole number of cents.
4. The **loyalty discount rate is selected once, from the prorated subtotal**, and is never re-selected from any later figure. A prorated subtotal of 5000 cents or more earns a rate of ten percent; a subtotal of at least 2000 cents but below 5000 earns five percent; anything below 2000 cents earns nothing.
5. The **discount** is the prorated subtotal multiplied by that rate, rounded half up to a whole cent, and the **discounted subtotal** is the prorated subtotal minus the discount.
6. The **processing fee** is 2.9 percent of the discounted subtotal, rounded half up to a whole cent, but never less than a 30-cent minimum — whichever of the two is larger is taken.
7. The **charge total** is the discounted subtotal plus the processing fee.

Only the subscription's own tier, its `current_period_end`, and the logical clock feed this computation; no other entity participates. The customer's `wallet_credit_cents` must be at least the charge total, or the request is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402). On success, `last_change_from_tier` records the tier held before the change, `tier` moves to the new tier immediately, the charge total is debited from `wallet_credit_cents`, `lifetime_charged_cents` is increased by the charge total, `last_change_charge_cents` is set to the charge total, and the subscription's `version` advances by one.

Reverting the most recent change is the compensating action for either direction. It requires that `last_change_charge_cents` is not null — if no change is outstanding, `ERR_INVALID_STATE` — and that `access_status` is not `CANCELLED`, likewise `ERR_INVALID_STATE`. The revert credits `last_change_charge_cents` back to `wallet_credit_cents`, decrements `lifetime_charged_cents` by that same amount, restores `tier` to `last_change_from_tier`, clears `pending_tier`, and finally sets both `last_change_charge_cents` and `last_change_from_tier` back to null. This is exactly the operation that keeps the wallet-plus-lifetime invariant of Section 2.10 intact.

### 3.3. Ordering a Kit and Activating Its Barcode

A customer orders a DNA kit for themselves by naming their `customer_id` and the `chip_version` the kit should be manufactured for — either `V4` or `V5`. The server mints a unique activation `barcode` and returns it on the created kit, whose `status` begins at `ORDERED` and whose `price_cents` is fixed at 9900. A kit's `activated_at` is null until activation. The kit lifecycle runs `ORDERED` → `ACTIVATED` → `RECEIVED` and then terminates at either `PROCESSED` or `VOID`; both terminal states are reached by the laboratory, not by the customer.

Activation is the customer echoing the printed barcode back. The payload carries a `barcode`, and four conditions must hold. The owning customer's `account_status` must not be `PURGED`, or the attempt fails with `ERR_CUSTOMER_PURGED`. The kit's `status` must be `ORDERED`; a kit that has already moved on rejects the attempt with `ERR_BARCODE_ALREADY_ACTIVATED`. The submitted `barcode` must equal the kit's own barcode exactly, or the attempt fails with `ERR_BARCODE_MISMATCH` (HTTP 422). And — this is a cross-entity dependency that surprises people — the kit owner's subscription must have an `access_status` of `ACTIVE` or `GRACE`, or activation is refused with `ERR_SUBSCRIPTION_LOCKED`. A locked account cannot start a test it has not paid for. On success the kit moves `ORDERED → ACTIVATED`, `activated_at` is stamped with the logical clock, and the kit's `version` advances by one.

When the swab physically arrives, a lab technician records receipt. This requires the kit to be in `ACTIVATED` status (`ERR_INVALID_STATE` otherwise) and moves it `ACTIVATED → RECEIVED`. Receipt is what brings a Sample into existence: a new sample is opened against that kit, referenced by its `kit_id`, with `status` of `RECEIVED` and `extraction_attempts` of 0. The owning customer's `dna_status`, which was `NO_SAMPLE`, becomes `PROCESSING`.

### 3.4. Extraction, QC Failure, and the Requeue Cycle

The laboratory's job is to turn a swab into usable DNA, and it frequently fails on the first try. A technician records an extraction attempt by submitting the `dna_yield_ng` recovered — the nanograms of DNA the attempt produced, which must be at least 0. The sample must be in `RECEIVED` status; anything else is `ERR_INVALID_STATE`. In every case, the submitted yield is written onto the sample's `dna_yield_ng` and `extraction_attempts` is incremented by one. What happens next depends on the yield and the attempt count together:

- A yield of at least 200.0 nanograms clears quality control, and the sample moves `RECEIVED → EXTRACTED`. It is now eligible for batching.
- A yield below 200.0 nanograms fails quality control. If, after the increment, `extraction_attempts` is still below three, the sample moves `RECEIVED → QC_FAILED` and can be salvaged.
- A yield below 200.0 nanograms where, after the increment, `extraction_attempts` has reached three or more, is terminal: the sample moves `RECEIVED → FAILED_TERMINAL`, and the terminal-failure cascade fires (below).

The cycle edge is the requeue. A technician may return a `QC_FAILED` sample to the head of the pipeline, moving it `QC_FAILED → RECEIVED` so it can be extracted again. This requires the sample to be in `QC_FAILED` status (`ERR_INVALID_STATE` otherwise) and requires `extraction_attempts` to be strictly below three — a sample that has burned all three attempts is refused with `ERR_EXTRACTION_ATTEMPTS_EXHAUSTED`. Requeuing clears the sample's `batch_id` back to null and clears its `call_rate` back to null, because whatever batch and whatever call rate the sample previously carried are no longer meaningful.

**The terminal-failure cascade** runs three hops and reaches into the customer's wallet. When a sample reaches `FAILED_TERMINAL` — whether from a failed extraction here or from a failed genotype call in Section 3.5 — its kit, sitting in `RECEIVED`, transitions to `VOID`. That kit transition in turn credits the customer's `wallet_credit_cents` by the kit's `price_cents` of 9900 and resets the customer's `dna_status` to `NO_SAMPLE`. The customer is made whole for a test the lab could not complete, and the platform's view of them reverts to having no usable DNA.

### 3.5. Instruments, Batches, and the Genotyping Run

An operator registers a genotyping instrument with a `name`, the `chip_version` it reads (`V4` or `V5`), and an optional `status` of `ONLINE` or `MAINTENANCE`, defaulting to `ONLINE`.

A technician creates a genotyping batch by naming the `instrument_id`, the run window boundaries `run_start_at` and `run_end_at`, and the list of `sample_ids` to enqueue. The window is **half-open**: it includes its start instant and excludes its end instant, which means back-to-back batches on the same instrument — where one batch's `run_start_at` equals the previous batch's `run_end_at` — do not conflict and are perfectly legal. Any genuine overlap with an existing batch on the same instrument whose `status` is `OPEN`, `RUNNING`, or `FINALIZED` is refused with `ERR_BATCH_WINDOW_OVERLAP`, as is a window whose end is not strictly after its start. Aborted batches release their window and never conflict. The instrument must be `ONLINE`; an instrument in `MAINTENANCE` yields `ERR_INSTRUMENT_OFFLINE`.

Every enumerated sample must be in `EXTRACTED` status, and — the chip constraint — the `chip_version` of the sample's kit must equal the `chip_version` of the batch's instrument. A sample that fails either test is refused with `ERR_SAMPLE_NOT_READY`. Each accepted sample moves `EXTRACTED → QUEUED`, has its `batch_id` set to the new batch, and pushes the batch's `member_count` up by one. The batch itself is created in `OPEN` status with `pass_rate` null.

Starting the run requires the batch to be `OPEN` (`ERR_INVALID_STATE` otherwise) and to have at least one member — a batch with `member_count` of zero is refused with `ERR_EMPTY_BATCH` (HTTP 422) — and requires the instrument to still be `ONLINE`, or `ERR_INSTRUMENT_OFFLINE`. The batch moves `OPEN → RUNNING`, and every member sample moves `QUEUED → GENOTYPING` with it.

Finalizing the run carries `sample_results`, an array with exactly one entry per member sample and no entries for anything else; a mismatch is `ERR_INVALID_REQUEST`. Each entry names a `sample_id` and reports that sample's `call_rate`, its `population_scores`, and its `genotype_markers`. The batch must be `RUNNING`, or `ERR_INVALID_STATE`. The `population_scores` is an array of entries each pairing a `population` code with an integer `raw_score`, and it is the raw material of every ancestry report the customer will ever receive. The `genotype_markers` is an ascending array of distinct integer marker positions, and it is what makes relative matching possible at all.

Each member sample's fate at finalize is decided by its call rate against a floor of 0.98, the same three-way split as extraction:

- A `call_rate` of at least 0.98: the sample moves `GENOTYPING → GENOTYPED`, and its `call_rate`, `population_scores`, and `genotype_markers` are all written from the result entry. The **finalize cascade** then fires: the sample's kit, sitting in `RECEIVED`, moves to `PROCESSED`, and that kit transition in turn sets the owning customer's `dna_status` to `DNA_READY`. The customer can now generate reports and be matched.
- A `call_rate` below 0.98 where the resulting `extraction_attempts` (after being incremented by one) is still below three: the sample moves `GENOTYPING → QC_FAILED`, with its `call_rate` written from the result entry. It can be requeued.
- A `call_rate` below 0.98 where the resulting `extraction_attempts` has reached three or more: the sample moves `GENOTYPING → FAILED_TERMINAL`, and the terminal-failure cascade of Section 3.4 fires — kit to `VOID`, 9900 cents back to the wallet, `dna_status` back to `NO_SAMPLE`.

The batch itself moves `RUNNING → FINALIZED` and records its `pass_rate`: the number of member samples whose reported call rate is at least 0.98, divided by the total number of member samples, rounded half up to 4 decimal places. Every sample that was in the batch counts in the denominator regardless of outcome. The denominator can never be zero, because a batch cannot reach `RUNNING` without at least one member.

A batch may also be aborted, from either `OPEN` or `RUNNING` (any other status is `ERR_INVALID_STATE`), moving it to `ABORTED`. Every member sample is released back to `EXTRACTED` — from `QUEUED` if the batch was open, from `GENOTYPING` if it was running — each member's `batch_id` is cleared to null, and the batch's `member_count` is set to zero. The samples are unharmed and may be re-batched elsewhere.

### 3.6. Granting and Withdrawing Consent

A customer grants a consent scope by naming their `customer_id`, the `scope` (`HEALTH_TRAITS`, `RELATIVE_MATCHING`, or `RESEARCH`), and the window boundaries `effective_from` and `effective_until`. The grant window is a **closed interval**: it includes both endpoints. A new grant is created in `ACTIVE` status with `withdrawn_at` null, and the customer's three consent booleans are recomputed immediately.

Two temporal rules guard grant creation, and their boundary semantics are deliberately opposite to those of the batch window. First, **overlap**: the new grant's closed window must not intersect the closed window of any existing `ACTIVE` grant for the same customer and the same scope. Because both intervals are closed, two grants that merely touch at an endpoint — where the new grant's `effective_from` equals an existing grant's `effective_until` — *do* intersect, and the request is rejected with `ERR_CONSENT_OVERLAP`. Second, the **cooling-off buffer**: if any `WITHDRAWN` grant exists for the same customer and the same scope, the new grant's `effective_from` must be at least 24 hours after the latest `withdrawn_at` among them. The boundary is inclusive — a new window beginning exactly 24 hours after the withdrawal is accepted, and anything earlier is rejected with `ERR_CONSENT_COOLING_OFF`. A customer whose `account_status` is `PURGED` cannot grant consent at all (`ERR_CUSTOMER_PURGED`).

Withdrawal moves a grant `ACTIVE → WITHDRAWN` — an `ACTIVE` grant is required, or `ERR_INVALID_STATE` — stamps `withdrawn_at` with the logical clock, and then does the work that gives withdrawal its teeth. What follows depends on the scope of the grant that was withdrawn:

- **`HEALTH_TRAITS`**: every report belonging to that customer whose `report_type` is `HEALTH_TRAIT` and whose `status` is `PUBLISHED` transitions to `REVOKED`.
- **`RESEARCH`**: every report belonging to that customer whose `variant` is `FINAL` and whose `status` is `PUBLISHED` transitions to `REVOKED`.
- **`RELATIVE_MATCHING`**: the four-hop suppression cascade fires, described in Section 3.7.

Revoking published reports is not cosmetic — because the subscription's `published_report_count` is a recomputed count of currently-`PUBLISHED` reports in the current period, a revocation reduces it, and that in turn changes which variant of the cancellation refund the customer would receive. A privacy officer may withdraw a grant on a customer's behalf; the cascades are identical either way.

Re-granting `RELATIVE_MATCHING` consent runs a cascade of its own, in three hops. First, the customer's `matching_opt_in` becomes true, provided the new grant's window covers the current logical-clock instant. Second, every relative match involving that customer that currently sits in `SUPPRESSED` status, and whose *other* side also has `matching_opt_in` true, transitions `SUPPRESSED → ACTIVE`. A suppressed match whose counterpart is still opted out stays suppressed — consent is required from both sides. Third, because those matches became active again, both customers on each reactivated pair have their `visible_match_count` incremented by one, restoring the doubling invariant of Section 2.10.

### 3.7. Ancestry and Health Reports

A customer generates a report by naming a `report_type` — `ETHNICITY` or `HEALTH_TRAIT` — a `variant` — `PROVISIONAL` or `FINAL` — and the `expected_customer_version` of Section 2.7. A report is created in `DRAFT` status and auto-published within the same request once its content has been computed, so the persisted result the client sees is already `PUBLISHED` with `generated_at` stamped from the logical clock. When a report of the same `report_type` was already `PUBLISHED` for that customer, that older report transitions `PUBLISHED → SUPERSEDED`. Both `SUPERSEDED` and `REVOKED` are terminal for a report. Publishing a report also advances the *customer's* own `version` by one — which means a client that wants to generate a second report must re-read the customer to obtain a fresh version, exactly as the stale-version guard of Section 2.7 intends. It likewise refreshes the subscription's `published_report_count`, the recomputed tally of reports currently `PUBLISHED` within the current billing period.

The report is computed from exactly one sample, chosen by a **source-sample selector** that also governs matching. Among the customer's samples — reachable through the kits they own — the eligible ones are those whose `status` is `GENOTYPED` and whose kit's `status` is `PROCESSED`. The eligible sample with the latest `created_at` wins; if two tie on creation time, the one with the higher `call_rate` wins. The sample's identifier is recorded on the report as `sample_id`. A sample's own identifier never participates in the selection. If no eligible sample exists, the customer is not genotyped and the request fails with `ERR_DNA_NOT_READY` (HTTP 409).

Three gates guard report generation beyond the stale-version check. The owning subscription's `access_status` must be `ACTIVE` or `GRACE`, and — additionally, for a `HEALTH_TRAIT` report — its `tier` must be `PLUS` or `PRO`, since health reporting is not an entitlement of the `FREE` tier; a failure of either yields `ERR_SUBSCRIPTION_LOCKED`. A `HEALTH_TRAIT` report additionally requires live `HEALTH_TRAITS` consent, and the `FINAL` variant additionally requires live `RESEARCH` consent; either missing gives `ERR_CONSENT_REQUIRED`.

**Health-trait reports** are simple to compute and consequential to permit. The report's `trait_count` is the number of entries in the source sample's `genotype_markers` whose value is at most 12. A health-trait report leaves `composition` as an empty array and `residual_population` null.

**Ethnicity reports** run the composition algorithm over the source sample's `population_scores`, and produce a `composition` array of entries each pairing a `population` code with a `share_pct`, sorted by population code in ascending order. The shares sum to exactly 100.00 by construction, and the mechanism that guarantees that is worth spelling out precisely, because the rounding order is pinned.

Start with the in-scope entries. Sum their raw scores to obtain a raw total. Then, **for each entry individually, round its share to 2 decimal places before summing anything** — a share is that entry's raw score divided by the raw total, multiplied by 100, rounded half up to 2 decimal places. Do not sum the unrounded shares and round once at the end; the two procedures give different answers, and only the first is correct here. Iterate the entries in ascending population-code order.

Next, assign the residual. Subtract the sum of the per-entry rounded shares from exactly 100.00 and round the difference half up to 2 decimal places. If that residual is not zero, it must be absorbed: the winner is the in-scope entry with the **largest raw score**, breaking any tie by taking the alphabetically lowest population code. The winner's share has the residual added to it, rounded half up to 2 decimal places, and the winner's population code is recorded on the report as `residual_population`. If the residual is zero, `residual_population` is null.

The two variants differ in which entries are in scope, and this is the whole of the difference:

- **`PROVISIONAL`**: every population in the sample's `population_scores` is in scope, including sub-one-percent trace populations. Shares are computed over the full raw total. This variant is always permitted once the customer is genotyped.
- **`FINAL`**: first compute the provisional shares over the full entry set exactly as above. Then **drop every entry whose provisional share is below 1.00 percent**, and re-run the entire three-step procedure — raw total, per-entry rounding, residual assignment — over only the surviving entries. Because the raw total has shrunk, the surviving populations are renormalized upward, producing different share values, and potentially a different `residual_population`, from what `PROVISIONAL` would have produced for the very same `population_scores`. This is the recalibration that requires `RESEARCH` consent.

### 3.8. DNA-Relative Matching

Matching is a recompute operation, run on behalf of a customer against every other customer on the platform. The acting customer must have `dna_status` of `DNA_READY`, or the run fails with `ERR_DNA_NOT_READY`, and must have `matching_opt_in` true, or it fails with `ERR_CONSENT_REQUIRED`. Candidate counterparts are every *other* customer whose `account_status` is `ACTIVE`, whose `dna_status` is `DNA_READY`, and whose `matching_opt_in` is true. A counterpart for whom the source-sample selector of Section 3.7 finds nothing eligible is silently skipped — that is not an error. The run returns the acting customer's matches afterward.

For each candidate pair, the **shared-segment scan** runs against the two source samples. Intersect the two customers' `genotype_markers` sets and sort the shared markers ascending. The shared centimorgan figure, `shared_cm`, is 4.00 centimorgans per shared marker, multiplied by the number of shared markers, rounded half up to 2 decimal places. The `segment_count` is the number of maximal runs of consecutive integers within the shared marker set — shared markers of 3, 4, 5, 10, and 11 form two runs, namely 3-4-5 and 10-11, so the segment count is 2.

A relative match is created if and only if `shared_cm` is **at least 8.00** — the boundary is inclusive, so exactly 8.00 does create a match while 4.00 does not. Below that threshold, nothing is created and nothing is an error.

The pair is ordered deterministically before it is stored. `customer_a_id` is the side of the pair whose customer record has the earlier `created_at`; if the two were created at the same instant, it is the side with the lexicographically lower `email`. `customer_b_id` is the other side. Customer identifiers are never used as an ordering or tie-break input. A pair is never duplicated: if a match already exists for the same two customers, it is **updated in place** — its `shared_cm`, `segment_count`, `confidence_score`, and `predicted_relationship` refreshed — rather than created afresh.

The **relationship ladder** then classifies the pair from `shared_cm`, first threshold matched wins, evaluated from the top: at least 240.00 centimorgans is `PARENT_CHILD`; at least 120.00 is `SIBLING`; at least 40.00 is `CLOSE_COUSIN`; at least 8.00 is `DISTANT_COUSIN`. The result is stored as `predicted_relationship`.

The **confidence score** weighs three factors. The first is a centimorgan factor: `shared_cm` divided by 400.00, capped at 1.0 — a pair sharing 400 or more centimorgans gets the full factor. The second is a segment factor: the pair's `segment_count` divided by the number of segments expected for its predicted relationship, capped at 1.0. The expected segment counts are 40 for `PARENT_CHILD`, 30 for `SIBLING`, 12 for `CLOSE_COUSIN`, and 4 for `DISTANT_COUSIN`. The third is a chip penalty: if the `chip_version` of the kit behind side A's source sample differs from the `chip_version` of the kit behind side B's source sample, a penalty of 0.05 applies; if the chips agree, the penalty is zero. The score is then seven tenths of the centimorgan factor plus three tenths of the segment factor, minus the chip penalty, floored at zero, and rounded half up to 4 decimal places.

Creating a new active match has two consequences. Both customers' `visible_match_count` is incremented by one — the count is, at all times, the number of matches in `ACTIVE` status naming that customer on either side of the pair, and it never goes below zero. And, for each side of the pair that owns an active family tree, a record hint is planted: a hint of `hint_type` `DNA_TREE` in `PENDING` status, whose `source_match_id` names the match that produced it and whose `confidence` is a copy of the match's `confidence_score`. The hinted person's `hint_count` is incremented by one.

Which person receives the hint is decided by a **root-person selector** with two stages, and neither stage ever uses an identifier as an input. First choose the tree: among the side's family trees whose `status` is `ACTIVE`, take the one with the earliest `created_at`, breaking ties by the alphabetically lowest tree `name`. If that side owns no active tree, no hint is created for that side and no error is raised. Then choose the person within that tree: among the tree's people whose `status` is `ACTIVE` and whose `father_id` and `mother_id` are both null — the roots of the tree — take the one with the earliest `created_at`, breaking ties by the alphabetically lowest `surname`. If the tree has no such root person, again no hint is created for that side, silently.

**Suppression** is the second hop of the consent-withdrawal cascade of Section 3.6, and it runs two further hops of its own. When one side's `matching_opt_in` becomes false, every `ACTIVE` match involving that customer transitions `ACTIVE → SUPPRESSED`. Because the match left `ACTIVE`, both sides' `visible_match_count` is decremented by one — the counterpart, who consented to nothing and did nothing, sees their relative count drop. And because the match left `ACTIVE`, every `PENDING` record hint whose `source_match_id` names that match transitions `PENDING → WITHDRAWN`, and the `hint_count` of the tree person each such hint hung from is decremented by one. Suppression is reversible: a re-grant walks the same path backwards, as described at the end of Section 3.6.

`PURGED` is the terminal state of a match and is reached only from the deferred deletion of Section 3.9.

### 3.9. Family Trees, Record Hints, and Accepting a Relative

A customer creates a family tree by naming their `customer_id` and a `name` for it. The tree begins in `ACTIVE` status — the only other status is `ARCHIVED` — with a `person_count` of zero.

Adding a person to a tree means naming the `tree_id` and supplying a `given_name` and a `surname`, optionally a `birth_year`, optionally the `father_id` and `mother_id` linking the person to their parents already in the tree, and optionally a `linked_customer_id` when the person is a known platform customer. A person is created in `ACTIVE` status — the alternative is `REMOVED` — with a `hint_count` of zero.

Two constraints guard the addition. The **cycle rule**: a `father_id` or `mother_id` must point at a person in the same tree, and must not make the new person its own ancestor by any path through the parent graph. Either violation is `ERR_TREE_CYCLE` (HTTP 422). The **tier person limit**: the tree's `person_count` — which counts only the tree's `ACTIVE` people — plus the one being added must not exceed the limit granted by the owner's subscription tier. That limit is 3 people on `FREE`, 250 on `PLUS`, and 999999 on `PRO`. Exceeding it is `ERR_TREE_PERSON_LIMIT` (HTTP 422). A successful addition increments the tree's `person_count` by one.

Record hints are never created by a client. They arrive only through the matching cascade of Section 3.8, and the only way to discover them is to list them — filtering by the `person_id` they are attached to, by the `source_match_id` that produced them, or by their `status`, which is one of `PENDING`, `ACCEPTED`, or `WITHDRAWN`. Beyond `DNA_TREE`, the `hint_type` enumeration also admits `CENSUS` for non-DNA provenance, in which case `source_match_id` is null.

Accepting a hint is how a DNA relative becomes a person in the tree. The hint must be `PENDING` (`ERR_INVALID_STATE` otherwise), the acting customer must own the family tree of the person the hint is attached to (`ERR_NOT_RESOURCE_OWNER` otherwise), and the tree's `person_count` plus one must fit within the tier person limit — the same limit and the same `ERR_TREE_PERSON_LIMIT` rejection as a manual addition, which means a `FREE`-tier customer with three people in their tree cannot accept a hint at all. On acceptance the hint moves `PENDING → ACCEPTED`, the `hint_count` of the person it hung from is decremented by one, and a new tree person is created in the same tree: their `given_name` is the counterpart customer's `display_name`, their `surname` is the literal string `DNA_MATCH`, their `linked_customer_id` names the counterpart customer, both `father_id` and `mother_id` are null, and their `status` is `ACTIVE`. The tree's `person_count` increments by one.

### 3.10. Data Export, Deferred Deletion, and the Purge Run

A customer files a privacy request by naming their `customer_id` and a `request_type` of either `EXPORT` or `DELETE`. The request is created in `PENDING` status with `reviewed_by`, `scheduled_purge_at`, and `export_url` all null. A customer may only ever have one request open at a time: if any of their existing requests is in `PENDING` or `SCHEDULED` status, the new filing is refused with `ERR_PENDING_DATA_REQUEST` (HTTP 409).

A privacy officer decides a `PENDING` request (any other status is `ERR_INVALID_STATE`) by submitting a `decision` of either `APPROVE` or `REJECT`. In all three outcomes the officer's `X-User-ID` is recorded in `reviewed_by`. A `REJECT` decision moves the request `PENDING → REJECTED` and nothing further happens. An `APPROVE` decision branches on the request type:

- For an `EXPORT` request, the approval completes immediately: the request moves `PENDING → COMPLETED`, and `export_url` is minted as the literal prefix `https://export.dna.example/` followed by the request's own identifier. Its `scheduled_purge_at` stays null.
- For a `DELETE` request, the approval schedules rather than executes: the request moves `PENDING → SCHEDULED`, and `scheduled_purge_at` is set to the current logical-clock instant plus seven days. Its `export_url` stays null. Approval is an instantaneous intermediate step — the status a client will read back is `SCHEDULED`, never `APPROVED`.

That seven-day gap is a grace period, and the customer may use it. A customer may cancel their own request from `PENDING` status, and from `SCHEDULED` status provided the current logical-clock instant is strictly before `scheduled_purge_at`. A request that has passed its purge instant can no longer be cancelled, and a request in any other status cannot either; both refusals are `ERR_INVALID_STATE`. A customer cancelling someone else's request gets `ERR_NOT_RESOURCE_OWNER`. Cancellation moves the request to `CANCELLED`, which along with `COMPLETED` and `REJECTED` is terminal.

The purge itself never fires on its own. An operator runs a purge checkpoint, which sweeps every request whose `status` is `SCHEDULED` and whose `scheduled_purge_at` is at or before the current logical-clock instant — the boundary is inclusive, so a request whose purge instant equals the clock exactly is executed. Requests in `PENDING`, `CANCELLED`, `REJECTED`, or `COMPLETED` status are ignored entirely. Eligible requests are processed in ascending order of their `created_at`, with ties broken by the ascending `email` of the requesting customer; a request's own identifier is never an input to the ordering. The run reports how many customers it purged as `purged_count` and echoes the identifiers of the requests it completed as `completed_request_ids`. When nothing is eligible, the count is zero and the list is empty.

Purging a customer is the widest cascade in the system. Their request moves `SCHEDULED → COMPLETED`. Their `account_status` and `dna_status` both become `PURGED`. Every one of their consent grants still in `ACTIVE` status transitions to `WITHDRAWN`. Every one of their reports in `DRAFT` or `PUBLISHED` status transitions to `REVOKED`. Every relative match naming them on either side transitions to `PURGED` — and each such match carries its own consequences outward: if the match was `ACTIVE` at the moment of purge, both sides' `visible_match_count` is decremented by one, so the surviving counterpart loses a relative they never knew they had; and every `PENDING` record hint whose `source_match_id` names that match transitions to `WITHDRAWN`, decrementing by one the `hint_count` of the tree person it was attached to. Finally, the purged customer's own `visible_match_count` is set to zero outright.

## 4. Endpoint Definitions

Endpoints that bring a new resource into existence respond with **201 Created**; every other successful operation, including state transitions, mutations of existing resources, and all reads, responds with **200 OK**. The table below is a routing summary only. The request payloads, response contents, and side effects of each operation are specified in the narrative of Sections 2 and 3, and must be read from there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/dna/customers` | Register a customer account. | `PlatformAdmin` |
| GET | `/dna/customers/{id}` | Read a customer, including store credit, DNA status, the three consent flags, visible match count and version. | `Customer`, `PlatformAdmin`, `PrivacyOfficer` |
| POST | `/dna/customers/{id}/credits` | Operator credit adjustment — tops up the customer's store credit. | `PlatformAdmin` |
| POST | `/dna/subscriptions` | Open a subscription for a customer. | `Customer`, `PlatformAdmin` |
| GET | `/dna/subscriptions/{id}` | Read a subscription, including both state dimensions, lifetime charges and version. | `Customer`, `PlatformAdmin` |
| GET | `/dna/subscriptions` | List subscriptions, filterable by owning customer and tier. | `Customer`, `PlatformAdmin` |
| POST | `/dna/subscriptions/{id}/change-tier` | Change the subscription tier. Upgrades apply immediately and are charged; downgrades are deferred at zero charge. Concurrency-guarded. | `Customer` |
| POST | `/dna/subscriptions/{id}/revert-change` | Compensating action for the most recent tier change. | `Customer` |
| POST | `/dna/subscriptions/{id}/billing-event` | Apply a billing event driving the two independent state dimensions. | `PlatformAdmin` |
| POST | `/dna/kits` | Order a DNA kit. The server mints the activation barcode and returns it. | `Customer` |
| GET | `/dna/kits/{id}` | Read a kit. | `Customer`, `PlatformAdmin`, `LabTechnician` |
| GET | `/dna/kits` | List kits, filterable by owning customer and status. | `Customer`, `PlatformAdmin`, `LabTechnician` |
| POST | `/dna/kits/{id}/activate` | Activate a kit by echoing its barcode. | `Customer` |
| POST | `/dna/kits/{id}/receive` | Lab records receipt of the swab and opens a sample. | `LabTechnician` |
| GET | `/dna/samples/{id}` | Read a sample, including extraction attempts, call rate, population scores and genotype markers. | `LabTechnician`, `PlatformAdmin`, `Customer` |
| GET | `/dna/samples` | List samples, filterable by kit, by batch and by status. | `LabTechnician`, `PlatformAdmin`, `Customer` |
| POST | `/dna/samples/{id}/extract` | Record a DNA extraction attempt. | `LabTechnician` |
| POST | `/dna/samples/{id}/requeue` | Return a QC-failed sample to the head of the pipeline. | `LabTechnician` |
| POST | `/dna/lab-instruments` | Register a genotyping instrument. | `PlatformAdmin` |
| GET | `/dna/lab-instruments/{id}` | Read an instrument. | `PlatformAdmin`, `LabTechnician` |
| POST | `/dna/lab-batches` | Create a genotyping batch occupying a run window on an instrument and enqueue extracted samples into it. | `LabTechnician` |
| GET | `/dna/lab-batches/{id}` | Read a batch, including member count and pass rate. | `LabTechnician`, `PlatformAdmin` |
| GET | `/dna/lab-batches` | List batches, filterable by instrument and status. | `LabTechnician`, `PlatformAdmin` |
| POST | `/dna/lab-batches/{id}/start` | Start the genotyping run. | `LabTechnician` |
| POST | `/dna/lab-batches/{id}/finalize` | Finalize the run with one result per member sample. | `LabTechnician` |
| POST | `/dna/lab-batches/{id}/abort` | Abort an open or running batch and release its members. | `LabTechnician` |
| POST | `/dna/consent-grants` | Grant a consent scope over a closed window. | `Customer` |
| GET | `/dna/consent-grants/{id}` | Read a consent grant. | `Customer`, `PrivacyOfficer` |
| GET | `/dna/consent-grants` | List consent grants, filterable by customer, scope and status. | `Customer`, `PrivacyOfficer`, `PlatformAdmin` |
| POST | `/dna/consent-grants/{id}/withdraw` | Withdraw a consent grant, driving the scope's cascade. | `Customer`, `PrivacyOfficer` |
| POST | `/dna/customers/{id}/reports` | Generate and publish a report from the customer's genotyped sample. Consent-gated and concurrency-guarded. | `Customer` |
| GET | `/dna/reports/{id}` | Read a report, including composition, residual population and trait count. | `Customer`, `PlatformAdmin` |
| GET | `/dna/reports` | List reports, filterable by customer, source sample, type and status. | `Customer`, `PlatformAdmin` |
| POST | `/dna/customers/{id}/matches/recompute` | Recompute the customer's DNA-relative matches against every other opted-in, DNA-ready customer. | `Customer`, `PlatformAdmin` |
| GET | `/dna/relative-matches/{id}` | Read a relative match. | `Customer`, `PlatformAdmin` |
| GET | `/dna/relative-matches` | List relative matches, filterable by either side of the pair and by status. | `Customer`, `PlatformAdmin` |
| POST | `/dna/family-trees` | Create a family tree. | `Customer` |
| GET | `/dna/family-trees/{id}` | Read a family tree, including person count. | `Customer`, `PlatformAdmin` |
| GET | `/dna/family-trees` | List family trees, filterable by owner and status. | `Customer`, `PlatformAdmin` |
| POST | `/dna/tree-people` | Add a person to a tree. | `Customer` |
| GET | `/dna/tree-people/{id}` | Read a tree person, including hint count. | `Customer`, `PlatformAdmin` |
| GET | `/dna/tree-people` | List tree persons, filterable by tree, by either parent link, by linked customer and by status. | `Customer`, `PlatformAdmin` |
| GET | `/dna/record-hints/{id}` | Read a record hint. | `Customer`, `PlatformAdmin` |
| GET | `/dna/record-hints` | List record hints, filterable by person, by source match and by status. | `Customer`, `PlatformAdmin` |
| POST | `/dna/record-hints/{id}/accept` | Accept a DNA hint, adding the matched relative to the tree. | `Customer` |
| POST | `/dna/data-requests` | File a data export or delete request. | `Customer` |
| GET | `/dna/data-requests/{id}` | Read a data request, including its scheduled purge instant and export URL. | `Customer`, `PrivacyOfficer` |
| GET | `/dna/data-requests` | List data requests, filterable by customer and status. | `Customer`, `PrivacyOfficer`, `PlatformAdmin` |
| POST | `/dna/data-requests/{id}/decide` | Privacy officer decision on a pending request. | `PrivacyOfficer` |
| POST | `/dna/data-requests/{id}/cancel` | Customer cancels their own pending or scheduled request. | `Customer` |
| POST | `/dna/_ops/purge-run` | Ops checkpoint: execute every due scheduled deletion. | `PlatformAdmin` |
| POST | `/dna/_clock/set_current_utc` | Set the server's logical clock. | `PlatformAdmin` |

Query parameters on the list endpoints are the filters named in the descriptions above, together with `limit` and `offset`. Concretely: subscriptions accept `customer_id` and `tier`; kits accept `customer_id` and `status`; samples accept `kit_id`, `batch_id`, and `status`; lab batches accept `instrument_id` and `status`; consent grants accept `customer_id`, `scope`, and `status`; reports accept `customer_id`, `sample_id`, `report_type`, and `status`; relative matches accept `customer_a_id`, `customer_b_id`, and `status`; family trees accept `customer_id` and `status`; tree people accept `tree_id`, `father_id`, `mother_id`, `linked_customer_id`, and `status`; record hints accept `person_id`, `source_match_id`, and `status`; and data requests accept `customer_id` and `status`.

## 5. Error Code Catalogue

The conditions that raise each of these codes are stated in the narratives of Sections 2 and 3, alongside the rule they enforce.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_SUBSCRIPTION_LOCKED` | 402 |
| `ERR_INSUFFICIENT_CREDIT` | 402 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_CONSENT_REQUIRED` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_KIT_NOT_FOUND` | 404 |
| `ERR_SAMPLE_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_INSTRUMENT_NOT_FOUND` | 404 |
| `ERR_CONSENT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_MATCH_NOT_FOUND` | 404 |
| `ERR_TREE_NOT_FOUND` | 404 |
| `ERR_PERSON_NOT_FOUND` | 404 |
| `ERR_HINT_NOT_FOUND` | 404 |
| `ERR_DATA_REQUEST_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_PURGED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BARCODE_ALREADY_ACTIVATED` | 409 |
| `ERR_DNA_NOT_READY` | 409 |
| `ERR_EXTRACTION_ATTEMPTS_EXHAUSTED` | 409 |
| `ERR_CONSENT_OVERLAP` | 409 |
| `ERR_CONSENT_COOLING_OFF` | 409 |
| `ERR_SAMPLE_NOT_READY` | 409 |
| `ERR_INSTRUMENT_OFFLINE` | 409 |
| `ERR_BATCH_WINDOW_OVERLAP` | 409 |
| `ERR_PENDING_DATA_REQUEST` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BARCODE_MISMATCH` | 422 |
| `ERR_EMPTY_BATCH` | 422 |
| `ERR_TREE_CYCLE` | 422 |
| `ERR_TREE_PERSON_LIMIT` | 422 |
