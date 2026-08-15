# Renewable REC Green Tariff API — Product Requirements Document

## 1. Introduction

Green power programs live or die on trust. A household paying a premium on its utility bill for renewable energy, and a regulator auditing a load-serving entity's compliance portfolio, both need the same proof: that every renewable energy certificate (REC) was minted from real metered generation, sold through a traceable chain of custody, retired at most once, and claimed in exactly one annual report. This document specifies the API of a green power program administrator that provides that proof end to end. The platform registers generation facilities, puts their meter readings through independent attestation, mints certificates under per-generator serial namespaces, settles broker trades between registry accounts, enrolls retail customers into green tariff programs with monthly bill credits, and closes the loop with retirements, compliance obligations, and audited annual claim reports.

Two market models share this single registry. In the voluntary market, a program operations desk runs green tariff programs whose subscribers receive bill credits and whose environmental claims are backed by voluntary retirements; in the compliance market, a compliance desk tracks annual renewable-portfolio obligations of load-serving entities and closes them out each year, assessing a shortfall penalty wherever coverage falls short. Broker desks move certificate batches between accounts under a dual settlement convention, and an independent auditor approves or rejects the annual claim reports that aggregate retirements for public disclosure. Strict segregation of duties, optimistic concurrency control on contended writes, and an entirely deterministic integer-arithmetic regime keep the registry audit-grade.

All endpoints are mounted under the `/greenpower` prefix. Every temporal rule in the system — attestation windows, settlement deadlines, vintage eligibility, billing months, current-year retirement totals — is evaluated against a server-maintained logical clock rather than wall-clock time, so the entire platform behaves reproducibly under test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request with missing headers, or whose role value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint — or that fails an ownership, purpose, or scope match described below — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Seven roles are recognized:

- `RegistryAdmin` — the registry and platform operator: verifies generators, administers programs and accounts, runs mint runs, accepts and voids meter readings, revokes certificates, expires trades, and drives the logical clock.
- `GeneratorOperator` — operates a single generation facility and speaks for its meter data.
- `MeterAttester` — independent attester of meter data who may never attest or reject a reading they themselves submitted.
- `BrokerTrader` — broker desk trader who proposes, accepts, settles, and cancels trades and performs wholesale-claim retirements.
- `ProgramManager` — runs green tariff program operations: subscriptions, billing, voluntary retirements, and voluntary claim reports.
- `ComplianceOfficer` — runs the compliance desk: obligations, compliance retirements, and compliance claim reports.
- `Auditor` — independent claims auditor who may never decide a report submitted by the same user.

Identity semantics differ by role. When `X-User-Role` is `GeneratorOperator`, `X-User-ID` is the `id` of the `Generator` they operate; ownership checks on any resource that references a generator compare that generator's `id` to `X-User-ID`. A `GeneratorOperator` therefore submits verification only for their own generator, creates meter readings only for their own generator, and resubmits only readings whose `submitted_by_user_id` equals their own `X-User-ID`. When `X-User-Role` is `BrokerTrader`, `X-User-ID` is the `id` of the `BROKER`-type `Account` they trade for; ownership checks compare account references to `X-User-ID`. Proposing a trade requires `X-User-ID` to equal the trade's `from_account_id`; accepting or settling a trade requires it to equal the `to_account_id`; cancelling a proposed trade requires it to equal the `from_account_id`; and a direct certificate transfer requires it to equal the certificate's `account_id`, although a `RegistryAdmin` may transfer any certificate regardless. A `WHOLESALE_CLAIM` retirement likewise requires the calling `BrokerTrader` to be the certificate's current holder account. For the remaining roles — `RegistryAdmin`, `MeterAttester`, `ProgramManager`, `ComplianceOfficer`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it (for example as `submitted_by_user_id` on a reading or a report, or as `attested_by_user_id` on a reading) but never compares it to any entity's `id`.

Purpose and scope tighten role checks further on two families of writes. Retirement creation requires the caller's role to match the declared `purpose`: `VOLUNTARY_PROGRAM` retirements are `ProgramManager`-only, `COMPLIANCE` retirements are `ComplianceOfficer`-only, and `WHOLESALE_CLAIM` retirements are `BrokerTrader`-only with the ownership match above. Claim-report creation, submission, and revision require a scope match: `ProgramManager` for the `VOLUNTARY_PROGRAM` scope and `ComplianceOfficer` for the `COMPLIANCE_OBLIGATION` scope.

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

### 2.3. Pagination and List Filtering

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100; a non-integer `limit` is rejected with `ERR_VALIDATION`, and an integer outside the 1–100 range is clamped to the nearest bound rather than rejected. The `offset` parameter sets the number of items skipped and defaults to 0; a non-integer `offset` is rejected with `ERR_VALIDATION`, and a negative integer is clamped to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally accept resource-appropriate equality filters. Generators filter by `status`, `technology`, and `region_code`; meter readings by `generator_id` and `status`; accounts by `account_type`, `generator_id`, `program_id`, and `status`; certificates by `generator_id`, `account_id`, `status`, `vintage_month`, and `region_code`; trades by `from_account_id`, `to_account_id`, and `status`; programs by `status`, `market_class`, and `holding_account_id`; subscriptions by `program_id` and `status`; bills by `subscription_id`, `status`, and `period_month`; retirements by `certificate_id`, `account_id`, `program_id`, `obligation_id`, and `purpose`; compliance obligations by `year`, `status`, and `region_code`; and claim reports by `program_id`, `obligation_id`, `status`, and `report_year`.

### 2.4. The Logical Clock

A server-maintained logical clock governs every time-dependent rule in this document: reading period bounds, the attestation window, settlement deadlines, vintage windows, billing months, proration day counts, and current-year retirement totals. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time. A `RegistryAdmin`-only test-driving capability moves the logical clock to any supplied ISO 8601 UTC instant provided in the request field `to_iso8601` — the clock may be moved to any such instant, forwards or backwards, with no monotonicity constraint; the response reports the new value in `current_utc` by echoing the request's `to_iso8601` string verbatim, and `meta.api_request_timestamp` of that response is likewise stamped from the newly set clock. Rules phrased as "now", "the clock month", or "the clock year" throughout this document always refer to this logical clock.

### 2.5. Common Resource Properties and Versioning

All primary resources — generators, meter readings, accounts, certificates, trades, programs, subscriptions, bills, compliance obligations, and claim reports — carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique across the registry.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource.

The `Retirement` resource is the deliberate exception: retirement rows carry only `id` and `created_at` of the common fields; both `updated_at` and `version` are absent, and no operation ever modifies a retirement row in place — in particular, when a claim report is accepted, the report stamps its own id onto each pinned retirement's `claimed_in_report_id` without giving the retirement an `updated_at` or a `version` (§3.9).

When a single request mutates several resources — accepting a reading also advances the generator's totals, settling a trade also rewrites certificates and account holdings — every touched resource refreshes its own `updated_at` and increments its own `version` by one. Where an automatic re-derivation is bundled into the same atomic mutation as a client-triggered change (for example, an obligation flipping to `MET` as a retirement lands), the combined mutation increments the affected resource's `version` exactly once for the whole request, never twice.

### 2.6. Registry Arithmetic: Units, Precision, and Rounding

The registry computes in whole units only. Energy is tracked in whole kilowatt-hours and whole megawatt-hours, money in whole cents, capacities in whole kilowatts, and certificate serials in whole numbers; no floating-point arithmetic appears anywhere in the system. Exactly two computations involve division, and both round the same way — half up to a whole cent: the calendar-day proration inside a final bill credit (the only division in billing), and each per-line broker fee inside a trade settlement (rounded per line before any summation takes place). Every other rule in this document — minting thresholds, coverage comparisons, shortfall penalties, serial ranges, waitlist arithmetic — is exact integer arithmetic with no rounding at all.

### 2.7. Optimistic Concurrency Control

Four writes are guarded by optimistic concurrency control, and each declares a non-optional request field that carries the client's last observed `version` of the parent entity being guarded:

- Enrolling a customer subscription requires `expected_program_version`, matched against the target program's current `version`. Because enrolling a subscription, activating one, terminating one, or amending the program all advance the program's `version`, this guard prevents a writer from enrolling against a capacity view it has not observed.
- Amending a generator's configuration requires `expected_generator_version`, matched against that generator's current `version`.
- Amending a program's configuration requires `expected_program_version`, matched against that program's current `version`.
- Amending a compliance obligation requires `expected_obligation_version`, matched against that obligation's current `version`.

In all four cases, a value that does not equal the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), and no part of the write is applied. Endpoints not listed here do not accept a version field at all.

### 2.8. Validation Pipeline and Error Ordering

Every write request traverses a fixed validation pipeline. A failure at any stage short-circuits the rest, so the error a client sees is always the earliest applicable one. The stages, in order, are:

1. Authentication — the headers are present and the role is recognized (`ERR_UNAUTHENTICATED`).
2. Authorization and ownership — the role is permitted for the endpoint and any ownership, purpose, or scope match holds (`ERR_FORBIDDEN_ROLE`).
3. Request schema — all required fields are present and all types and enum values are valid (`ERR_VALIDATION`).
4. Existence — path identifiers are resolved first, validated left to right, and only then are the foreign keys referenced in the request body (`generator_id`, `program_id`, `subscription_id`, `certificate_id`, `from_account_id`, `to_account_id`, each `certificate_id` inside `items`, `obligation_id`, `holding_account_id`) resolved (`ERR_NOT_FOUND`).
5. Optimistic concurrency — on the four guarded writes, the expected parent version matches (`ERR_STALE_VERSION`).
6. State-machine admissibility — each entity involved is in the transition's required from-state, the generator is `ACTIVE` where ingestion requires it, the program is `OPEN`, participating accounts are `ACTIVE`, and the certificate is in an admissible disposition (`ERR_GENERATOR_NOT_ACTIVE`, `ERR_INVALID_GENERATOR_STATE`, `ERR_INVALID_READING_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_CERTIFICATE_NOT_ACTIVE`, `ERR_TRADE_STATE_INVALID`, `ERR_PROGRAM_NOT_OPEN`, `ERR_SUBSCRIPTION_STATE_INVALID`, `ERR_BILL_STATE_INVALID`, `ERR_OBLIGATION_NOT_OPEN`, `ERR_REPORT_STATE_INVALID`).
7. Segregation of duties — attestation and report decision makers differ from submitters (`ERR_SELF_ATTESTATION`, `ERR_SELF_APPROVAL`).
8. Double-count guard — a submitting report's pinned retirements are all unclaimed (`ERR_DOUBLE_COUNT`).
9. Temporal rules — period orientation, future periods, interval overlap, attestation and settlement windows, expiry eligibility, and vintage windows (`ERR_PERIOD_INVERTED`, `ERR_FUTURE_PERIOD`, `ERR_READING_PERIOD_OVERLAP`, `ERR_ATTESTATION_WINDOW_EXPIRED`, `ERR_SETTLEMENT_WINDOW_EXPIRED`, `ERR_TRADE_NOT_EXPIRED`, `ERR_VINTAGE_INELIGIBLE`).
10. Eligibility and uniqueness constraints — region and technology eligibility, uniqueness of claim references, bills, utility accounts, and reports, quantity sanity, market class, and non-empty reports (`ERR_REGION_INELIGIBLE`, `ERR_TECHNOLOGY_INELIGIBLE`, `ERR_DUPLICATE_CLAIM_REFERENCE`, `ERR_DUPLICATE_BILL`, `ERR_DUPLICATE_UTILITY_ACCOUNT`, `ERR_DUPLICATE_REPORT`, `ERR_QUANTITY_INVALID`, `ERR_MARKET_CLASS_MISMATCH`, `ERR_REPORT_EMPTY`).
11. Fiscal caps — allocation against program capacity and report totals against the annual claim cap (`ERR_ALLOCATION_EXCEEDS_CAP`, `ERR_CLAIM_CAP_EXCEEDED`).
12. Referential guards — minted readings, live subscriptions, and wired holding accounts (`ERR_READING_ALREADY_MINTED`, `ERR_PROGRAM_HAS_ACTIVE_SUBSCRIPTIONS`, `ERR_PROGRAM_HOLDING_ACCOUNT_MISSING`).

The practical consequences matter. A meter reading submitted for a suspended generator fails with `ERR_GENERATOR_NOT_ACTIVE` before its period bounds are ever examined. A reading whose period runs backwards reports `ERR_PERIOD_INVERTED` before any future-period or overlap consideration. An attestation attempted on a reading in the wrong state reports `ERR_INVALID_READING_STATE` even when the caller would also trip the segregation-of-duties rule, because state checks precede duty checks. On a settlement, account standing is verified before the trade's own state-machine position, so a suspended buyer surfaces `ERR_ACCOUNT_NOT_ACTIVE` rather than `ERR_TRADE_STATE_INVALID`. On a voluntary retirement, the vintage window is evaluated before the region rule, which in turn is evaluated before the technology rule. And a claim report submission runs its double-count guard before the empty-report and claim-cap checks — safety before fiscal.

### 2.9. Certificate Identity: Serial Namespaces, Snapshots, and Conservation

Every certificate batch occupies a contiguous run of whole-REC serial numbers inside its minting generator's private serial space. The batch's `serial_prefix` joins the generator's `facility_code` and the batch's `vintage_month` with a hyphen separator, and the run extends from `serial_start` through `serial_end`, both inclusive, so that `serial_end` always equals `serial_start` plus `quantity_mwh` minus one — a batch of N units occupies exactly N consecutive serials. A generator's `next_serial` begins at 1 and advances by the minted quantity with every batch; serial numbers are never reused, and revoking certificates reduces `lifetime_minted_mwh` without rewinding `next_serial`.

Certificates are historical records, not mirrors of their generator. `vintage_month`, `region_code`, and `technology` are snapshots taken at mint time; later amendments to the generator's configuration — including a `region_code` change — never retro-alter certificates already minted. The same snapshot discipline applies to retirement rows, which freeze `quantity_mwh`, `vintage_month`, `region_code`, and `technology` from the certificate at retirement time and are immutable thereafter.

Conservation governs every certificate mutation. Splitting a batch at settlement partitions its serial range into two ranges with no gap and no overlap, and the two resulting quantities sum exactly to the original `quantity_mwh`. Locking, transferring, retiring, and revoking move whole quantities between an account's `active_holdings_mwh` and `locked_holdings_mwh` or out of holdings entirely, but never create or destroy units except minting (which creates) and retirement or revocation (which removes from circulation).

## 3. Business Logic & Workflows

### 3.1. Generator Onboarding and Lifecycle

A `RegistryAdmin` registers a generation facility by supplying its `legal_name`, a `facility_code` that must be unique across all generators, the generation `technology` (one of `SOLAR`, `WIND`, `HYDRO`, `BIOMASS`, or `GEOTHERMAL`), the `nameplate_capacity_kw` as a positive integer, the balancing-authority `region_code` (for example CAISO, ERCOT, or PJM), and the `commissioning_date` in `YYYY-MM-DD` form. A duplicate `facility_code` is rejected with `ERR_VALIDATION`. A new generator starts in `REGISTERED` status with `rejection_reason` unset, `cumulative_accepted_kwh` and `carryover_kwh` at zero, the minted total `lifetime_minted_mwh` at zero, and `next_serial` at 1. The `cumulative_accepted_kwh` field is derived at read time (see §3.2).

When the operator is ready for review, the `GeneratorOperator` owning the generator submits it for verification, moving it from `REGISTERED` to `VERIFICATION`; a generator whose earlier attempt failed may resubmit from `REJECTED` to `VERIFICATION`, which also clears its `rejection_reason` back to unset. Both submissions require the caller's `X-User-ID` to equal the generator's `id`; a mismatch is rejected with `ERR_FORBIDDEN_ROLE`, and either attempt from any other state is rejected with `ERR_INVALID_GENERATOR_STATE`. A `RegistryAdmin` then decides the review. Verification moves the generator from `VERIFICATION` to `ACTIVE` and, as part of the same mutation, auto-creates its generator account: an `Account` with `account_type` `GENERATOR`, wired to the generator through `generator_id`, named after the generator's `legal_name` in `owner_name`, and starting in `ACTIVE` standing with `failure_strikes` at zero. Rejection moves the generator from `VERIFICATION` to `REJECTED` and records the supplied `reason` in `rejection_reason`.

Once live, a generator can be suspended and later reinstated by a `RegistryAdmin` — `ACTIVE` to `SUSPENDED` and `SUSPENDED` back to `ACTIVE` — and can be decommissioned from either `ACTIVE` or `SUSPENDED` into the terminal `DECOMMISSIONED` state. A decommissioned generator accepts no new meter readings: submission requires an `ACTIVE` generator and fails with `ERR_GENERATOR_NOT_ACTIVE` otherwise. Every lifecycle transition increments the generator's `version` by one and refreshes `updated_at`, and any lifecycle action — verification, rejection, suspension, reinstatement, or decommissioning — attempted from a state the transition does not allow is rejected with `ERR_INVALID_GENERATOR_STATE`.

A `RegistryAdmin` may also amend a registered generator's `legal_name`, `nameplate_capacity_kw`, or `region_code`. This write is guarded by `expected_generator_version` as described in §2.7, increments the generator's `version` by one, and — per §2.9 — a `region_code` amendment never retro-alters the snapshots on certificates already minted. It may be applied in any generator state, `DECOMMISSIONED` included.

### 3.2. Meter Readings: Submission, Attestation, and Acceptance

Meter data enters the registry through the `GeneratorOperator` who owns the generator. A submission names the `generator_id`, the metered period as a half-open interval from `period_start` (inclusive) to `period_end` (exclusive), both ISO 8601 UTC instants, and the `metered_kwh` delivered, expressed in whole kilowatt-hours. The generator must be `ACTIVE`, or the submission is rejected with `ERR_GENERATOR_NOT_ACTIVE`. The period must run forwards — `period_end` strictly after `period_start`, else `ERR_PERIOD_INVERTED` — and must not reach into the future: `period_end` may not be later than the logical clock, else `ERR_FUTURE_PERIOD`. For the same generator, the new interval may not overlap any existing reading in `SUBMITTED`, `ATTESTED`, or `ACCEPTED` status; the overlap test is the standard half-open one, so an existing reading whose `period_end` coincides exactly with the new reading's `period_start` is adjacency, not overlap, while any strict intersection of the two intervals is rejected with `ERR_READING_PERIOD_OVERLAP`. Finally, `metered_kwh` must be a positive integer, with non-positive values rejected as `ERR_QUANTITY_INVALID`; this quantity check is applied only after the three period rules, so a submission that both overlaps an existing reading and carries a non-positive quantity reports `ERR_READING_PERIOD_OVERLAP`. A reading that passes every check lands in `SUBMITTED` status with `submitted_by_user_id` recording the caller, `attested_by_user_id` and `rejection_reason` unset, `minted` false, and `minted_vintage_month` unset.

Attestation is performed by a `MeterAttester` under strict segregation of duties. Attesting moves a reading from `SUBMITTED` to `ATTESTED` and records the caller in `attested_by_user_id`; the caller's `X-User-ID` must differ from the reading's `submitted_by_user_id`, else the attempt is rejected with `ERR_SELF_ATTESTATION`. Attestation is also time-boxed: it is permitted only while the logical clock is no later than thirty days after `period_end`, and an attempt past that window is rejected with `ERR_ATTESTATION_WINDOW_EXPIRED`; the window is evaluated after the segregation-of-duties check, so an expired self-attestation reports `ERR_SELF_ATTESTATION`. Rejection is not time-boxed — the thirty-day window constrains attestation only. A `MeterAttester` may instead reject the reading, moving it from `SUBMITTED` — or from `ATTESTED`, if second thoughts arise — to `REJECTED`, recording the supplied `reason` in `rejection_reason` (the reason may be omitted, leaving it unset); rejecting an attested reading additionally clears its `attested_by_user_id` back to unset. The same segregation rule governs rejection: the submitter may never reject their own reading. Any attestation, rejection, resubmission, acceptance, or void attempted from a state the transition does not allow is rejected with `ERR_INVALID_READING_STATE`.

Rejection is not terminal. The owning `GeneratorOperator` — identified by `X-User-ID` matching `submitted_by_user_id` — may resubmit a `REJECTED` reading, returning it to `SUBMITTED` and clearing its `rejection_reason`. This revision cycle may repeat as often as needed.

Final acceptance belongs to the `RegistryAdmin`. Accepting moves a reading from `ATTESTED` to `ACCEPTED` and credits the generator: its `cumulative_accepted_kwh` — defined as the sum of `metered_kwh` over the generator's readings currently in `ACCEPTED` status — increases by the reading's `metered_kwh`, and both the reading's and the generator's `version` increment. Acceptance additionally requires the generator itself to be `ACTIVE`; a reading belonging to a suspended or decommissioned generator cannot be accepted — this generator-standing check is applied only after the reading's own state check, so an un-`ATTESTED` reading of a suspended generator reports `ERR_INVALID_READING_STATE`. Should an accepted reading prove erroneous, a `RegistryAdmin` may void it, moving it from `ACCEPTED` to the terminal `VOIDED` state, which debits the generator's `cumulative_accepted_kwh` by the same `metered_kwh` and again increments both versions. Voiding is possible only while the reading has not yet been consumed by a mint run: once `minted` is true, the attempt is rejected with `ERR_READING_ALREADY_MINTED`. A void request may carry an optional `reason` for the audit trail; when supplied, it is recorded into the reading's `rejection_reason` field, and when omitted the reading's `rejection_reason` is left as-is.

### 3.3. Minting Runs and Certificate Issuance

Certificates come into existence only through a mint run, executed by a `RegistryAdmin` against an `ACTIVE` generator — the run is rejected with `ERR_GENERATOR_NOT_ACTIVE` in any other generator state. One thousand kilowatt-hours make one REC, and minting consumes only accepted, unconsumed production: the run collects every reading of this generator in `ACCEPTED` status with `minted` still false — `SUBMITTED`, `ATTESTED`, `REJECTED`, and `VOIDED` readings never participate — and orders them by `period_start` ascending, breaking ties by `created_at` ascending.

Readings are then grouped into vintage buckets keyed by the calendar month of `period_start` in `YYYY-MM` form, and buckets are processed in chronological order. The run maintains a carry of un-minted kilowatt-hours that begins from the generator's stored `carryover_kwh`, tagged with the calendar year that produced it. Carryover never crosses a calendar-year boundary: if the first bucket of the run belongs to a later calendar year than the year that produced the stored carryover, that carryover is discarded to zero before processing begins. For each bucket in turn, the pool is the bucket's own summed `metered_kwh` plus any pending carry that was produced in the same calendar year as the bucket; a pending carry from a different year is discarded and the pool is the bucket's kilowatt-hours alone. The number of whole RECs in a pool is the pool divided by one thousand and rounded down.

Whenever that whole number is at least one, exactly one certificate batch is minted for the bucket. Its `quantity_mwh` is the whole number of RECs; its `vintage_month` is the bucket; its `region_code` and `technology` are snapshots of the generator's current configuration at mint time; its `serial_prefix` joins the generator's `facility_code` and the bucket month with a hyphen; its `serial_start` is the generator's current `next_serial`; and its `serial_end` is `serial_start` plus the minted quantity minus one. Ownership is assigned to the generator's own `GENERATOR` account, so the batch lands in that account's `active_holdings_mwh`. The generator's `next_serial` and `lifetime_minted_mwh` each advance by the minted quantity. The remainder — the pool minus one thousand times the minted quantity — becomes the carry into the next bucket, provided the next bucket lies in the same calendar year; otherwise it is discarded at the year boundary. Regardless of whether a bucket mints a certificate, every reading in a processed bucket is marked with `minted` true and `minted_vintage_month` set to its bucket, and each such marking mutates the reading, incrementing its `version` and refreshing its `updated_at`; a reading is never consumed twice. After the final bucket, the generator's `carryover_kwh` is set to the last computed carry, and both the generator's `updated_at` and `version` reflect the mutation.

The mint run responds with a summary object rather than a resource: `minted_count` batches created, `total_minted_mwh` whole RECs issued, the closing `carryover_kwh`, and the `certificate_ids` of the new batches in mint order. When no readings qualify, the run is not an error: it returns `minted_count` 0, `total_minted_mwh` 0, an empty `certificate_ids`, and the generator's unchanged `carryover_kwh`, without touching the generator's `version` or `updated_at`.

### 3.4. Broker Accounts, Trades, and Settlement Discipline

Registry accounts come in three kinds, recorded in `account_type`: `GENERATOR` accounts arise automatically when a generator is verified and are never created directly — an attempt to create one is rejected with `ERR_VALIDATION`; `BROKER` and `PROGRAM` accounts are created by a `RegistryAdmin`, who supplies the `owner_name` and wires a `PROGRAM` account to its program through `program_id` (a `GENERATOR` account likewise carries its `generator_id`). `program_id` is mandatory for a `PROGRAM` account and its absence is rejected with `ERR_VALIDATION`; any `generator_id` or `program_id` supplied on creation must reference an existing entity, else `ERR_NOT_FOUND`. Every account tracks two derived holdings figures — `active_holdings_mwh`, the summed `quantity_mwh` of its certificates in `ACTIVE` status, and `locked_holdings_mwh`, the same sum over certificates in `LOCKED` status, both recomputed on every read — and a `failure_strikes` counter of settlement failures attributed to it. Accounts begin in `ACTIVE` standing with `failure_strikes` at zero.

An account may be suspended by a `RegistryAdmin` (`ACTIVE` to `SUSPENDED`) and later reinstated (`SUSPENDED` to `ACTIVE`), with reinstatement resetting `failure_strikes` to zero; either action from the wrong state is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. Suspension also arrives automatically: the moment an account's `failure_strikes` reaches three, the account transitions to `SUSPENDED` on its own. Either way, suspension cancels every `PROPOSED` trade on which the account is the seller — those trades move to `CANCELLED` without touching any certificates, because no locks are taken while a trade is merely proposed.

Trades are the market's transfer mechanism. A `BrokerTrader` proposes a trade by naming the selling account in `from_account_id` — which must be their own `BROKER` account — the buying account in `to_account_id`, an `items` array whose elements each pair a `certificate_id` with a `quantity_mwh`, a single positive `unit_price_cents_per_mwh` applied to every line, and a `settlement_mode` of `GROSS` or `NET`. Both accounts must be `BROKER`-type registry accounts; naming a `GENERATOR` or `PROGRAM` account fails request validation with `ERR_VALIDATION`, and a seller account not owned by the caller is rejected with `ERR_FORBIDDEN_ROLE`. Every referenced certificate must be `ACTIVE` and currently held by the selling account, else `ERR_CERTIFICATE_NOT_ACTIVE`, and each line's `quantity_mwh` must be at least one and no more than that certificate's own `quantity_mwh`, with out-of-range quantities rejected as `ERR_QUANTITY_INVALID`. Both participating accounts must be in `ACTIVE` standing, else `ERR_ACCOUNT_NOT_ACTIVE`. The `items` array must be non-empty and each line's `quantity_mwh` an integer, else `ERR_VALIDATION`. A compliant proposal lands in `PROPOSED` status with `proposed_at` stamped from the logical clock; the monetary fields `total_line_cents`, `broker_fee_cents`, `buyer_total_cents`, and `seller_proceeds_cents` remain unset until settlement, and `accepted_at`, `settlement_deadline`, and `settled_at` are likewise unset. No certificates are locked at proposal time.

Acceptance belongs to the buyer. A `BrokerTrader` whose `X-User-ID` equals the trade's `to_account_id` may accept a `PROPOSED` trade, moving it to `ACCEPTED`, provided the buyer account is in `ACTIVE` standing — a suspended buyer fails with `ERR_ACCOUNT_NOT_ACTIVE` — and every item certificate is still `ACTIVE` and still held by the selling account: ownership can drift between proposal and acceptance, and any certificate that no longer qualifies fails the acceptance with `ERR_CERTIFICATE_NOT_ACTIVE` — a failure ordered so that a trade no longer in `PROPOSED` whose item certificates have also drifted reports `ERR_CERTIFICATE_NOT_ACTIVE` before `ERR_TRADE_STATE_INVALID`. Acceptance locks every item certificate atomically: all of them move from `ACTIVE` to `LOCKED` or none do, and the holder account's `locked_holdings_mwh` rises while its `active_holdings_mwh` falls by the locked quantities. Acceptance stamps `accepted_at` and fixes the `settlement_deadline` exactly five days later.

Settlement is likewise the buyer's move and is permitted only while the logical clock is at or before the `settlement_deadline`; a late attempt is rejected with `ERR_SETTLEMENT_WINDOW_EXPIRED`, and both accounts must still be in `ACTIVE` standing. For each item, the settled quantity moves to the buyer. When the item's quantity equals the certificate's whole quantity, the locked certificate row itself changes hands: its `account_id` becomes the buyer and its status returns from `LOCKED` to `ACTIVE`. When the item's quantity is smaller, the batch splits in two — the original row remains with the seller as the remainder, its `serial_start` advanced by the transferred quantity and its `quantity_mwh` reduced accordingly, returning from `LOCKED` to `ACTIVE`, while a brand-new certificate row is created for the transferred slice with `serial_start` equal to the original range's old start and `serial_end` equal to that old start plus the transferred quantity minus one, owned by the buyer and `ACTIVE`, copying `generator_id`, `vintage_month`, `region_code`, `technology`, and `serial_prefix` from the original. The two serial ranges partition the original range with no gap and no overlap, and the two quantities sum exactly to the pre-split `quantity_mwh`. Holdings on both the seller's and buyer's accounts are recomputed as ownership moves.

Money is computed only at settlement, with the rounding order pinned. For each item line in the order the items were proposed, the line total is the settled `quantity_mwh` multiplied by the trade's `unit_price_cents_per_mwh`, an exact integer product. The broker fee is computed per line and rounded per line before any summation: lines smaller than 100 MWh are charged 50 basis points, lines of at least 100 MWh but less than 1000 MWh are charged 35 basis points, and lines of 1000 MWh or more are charged 20 basis points; each line's fee is its line total multiplied by the applicable basis-point rate, divided by ten thousand, and rounded half-up to a whole cent. The trade's `total_line_cents` is the sum of the line totals and its `broker_fee_cents` is the sum of the rounded per-line fees — computing the fee on the aggregate total instead is a different, non-conformant algorithm and yields different cents. Under `settlement_mode` `GROSS`, the `buyer_total_cents` is the line total plus the broker fee and the `seller_proceeds_cents` is the full line total; under `NET`, the buyer pays the line total only and the `seller_proceeds_cents` is the line total minus the broker fee. Settlement stamps `settled_at` and moves the trade to the terminal `SETTLED` state.

Three exits exist for a trade that never settles. The seller may cancel a `PROPOSED` trade, moving it to `CANCELLED`; because nothing was locked, no certificate is touched. A `RegistryAdmin` may expire an `ACCEPTED` trade once the logical clock has passed its `settlement_deadline` — an expiry attempted at or before the deadline is rejected with `ERR_TRADE_NOT_EXPIRED` — moving it to `EXPIRED`, unlocking every item certificate from `LOCKED` back to `ACTIVE` with ownership unchanged, and adding one to the buyer account's `failure_strikes`; if that strike is the account's third, the buyer account auto-suspends and its own proposed trades cancel as described above. Finally, if a certificate referenced by an `ACCEPTED` trade is revoked, the trade fails: it moves to `FAILED`, every other item certificate not itself revoked unlocks from `LOCKED` to `ACTIVE`, and the seller account's `failure_strikes` increases by one, with the same three-strike suspension cascade. Any accept, settle, cancel, or expire attempted from a state the transition does not allow is rejected with `ERR_TRADE_STATE_INVALID`.

Certificate discipline completes the picture. A `RegistryAdmin` may revoke a certificate in `ACTIVE` or `LOCKED` status — a `RETIRED` or already `REVOKED` certificate is rejected with `ERR_CERTIFICATE_NOT_ACTIVE` — optionally recording a `reason`. Revoking an `ACTIVE` certificate decrements the holder's `active_holdings_mwh` by its `quantity_mwh`; revoking a `LOCKED` certificate decrements `locked_holdings_mwh` instead and additionally fails every `ACCEPTED` trade referencing it, triggering the failure cascade above; either path decrements the minting generator's `lifetime_minted_mwh` by the same quantity and moves the certificate to the terminal `REVOKED` state. Separately, a bilateral whole-batch transfer moves an `ACTIVE` certificate to another account named in `to_account_id` with no settlement and no split: a certificate in any other disposition is rejected with `ERR_CERTIFICATE_NOT_ACTIVE`; a `BrokerTrader` must own the certificate — `X-User-ID` equal to its `account_id` — while a `RegistryAdmin` may transfer any; the receiving account must be in `ACTIVE` standing, else `ERR_ACCOUNT_NOT_ACTIVE`, and this standing check is applied before the certificate's own disposition check, so transferring a locked certificate into a suspended account reports `ERR_ACCOUNT_NOT_ACTIVE`; the certificate keeps its `ACTIVE` status, its `account_id` is reassigned, holdings are recomputed on both accounts, and the certificate's `version` increments.

### 3.5. Green Tariff Programs and Customer Subscriptions

A green tariff program is created by a `RegistryAdmin` with a display `name`, a `market_class` of `VOLUNTARY` or `COMPLIANCE`, the `eligible_region_codes` and `eligible_technologies` arrays that gate voluntary retirements — every entry of `eligible_technologies` must be one of the five declared technologies, else `ERR_VALIDATION` — a positive `capacity_cap_kw` ceiling, the marginal `rate_tiers` array, and a positive `annual_claim_cap_mwh`. Two inputs carry defaults: `vintage_window_months` defaults to 12 when omitted, and `kwh_per_kw_monthly` — the deemed monthly generation per allocated kilowatt used in bill credits — defaults to 100; either, when supplied, must be a positive integer, else `ERR_VALIDATION`. The program's `holding_account_id`, which must eventually reference the `PROGRAM` account holding this program's certificates, may be left unset at creation; when supplied it must reference an existing account, else `ERR_NOT_FOUND`. Each entry of `rate_tiers` pairs an `up_to_kwh` upper bound — where a null bound means unbounded and a non-null bound must be a positive integer — with a non-negative integer `rate_cents_per_kwh`, violations of either rejected with `ERR_VALIDATION`; the array is ascending by `up_to_kwh`. A new program is in `DRAFT` status with `committed_capacity_kw` and `retired_mwh_current_year` at zero; both are derived figures recomputed on every read.

Opening a program moves it from `DRAFT` to `OPEN` and is only possible once `holding_account_id` references an existing account of `account_type` `PROGRAM` that is wired back to this program through its own `program_id`; opening without such a wired holding account is rejected with `ERR_PROGRAM_HOLDING_ACCOUNT_MISSING`. Archiving moves an `OPEN` program to the terminal `ARCHIVED` state and is refused with `ERR_PROGRAM_HAS_ACTIVE_SUBSCRIPTIONS` while any subscription of the program remains in `PENDING`, `ACTIVE`, `WAITLISTED`, or `SUSPENDED`. A `RegistryAdmin` may amend a program's `name`, `capacity_cap_kw`, `rate_tiers`, `eligible_region_codes`, `eligible_technologies`, `vintage_window_months`, `annual_claim_cap_mwh`, or `holding_account_id` — `holding_account_id` may also be amended to null, clearing it, while a non-null value must reference an existing account, else `ERR_NOT_FOUND`; the write is guarded by `expected_program_version` per §2.7 and increments the program's `version` by one, and raising `capacity_cap_kw` releases capacity, which fires the waitlist promotion scan described below. Amendment is permitted in any program state — `DRAFT`, `OPEN`, or `ARCHIVED`.

Customer enrollment is the `ProgramManager`'s work. Creating a subscription names the `program_id`, the `customer_name`, the `utility_account_no`, the subscribed `allocation_kw`, and the customer's declared `estimated_usage_kwh`, and it must carry `expected_program_version` per the optimistic-concurrency rule of §2.7. The program must be `OPEN`, else `ERR_PROGRAM_NOT_OPEN`, and its `market_class` must be `VOLUNTARY` — subscriptions into a `COMPLIANCE`-class program are rejected with `ERR_MARKET_CLASS_MISMATCH`. The `utility_account_no` must be unique among the program's non-`TERMINATED` subscriptions, else `ERR_DUPLICATE_UTILITY_ACCOUNT`. Both `allocation_kw` and `estimated_usage_kwh` must be positive integers, with violations rejected as `ERR_QUANTITY_INVALID`, and an `allocation_kw` larger than the program's entire `capacity_cap_kw` can never fit and is rejected outright with `ERR_ALLOCATION_EXCEEDS_CAP`. When an enrollment would trip several of these gates at once, they are evaluated in the order: program-open check, utility-account uniqueness, quantity sanity, market class, then the capacity ceiling. A successful enrollment lands in `PENDING` status with `activated_at`, `waitlisted_at`, and `terminated_at` unset — and it increments the program's `version` by one, so any other writer holding a stale program version fails its next guarded write with `ERR_STALE_VERSION`.

Activation is decided by capacity. Activating a `PENDING` subscription requires the program to be `OPEN` (again `ERR_PROGRAM_NOT_OPEN` otherwise). If the program's `committed_capacity_kw` — the summed `allocation_kw` over its `ACTIVE` and `SUSPENDED` subscriptions — plus the new `allocation_kw` fits within `capacity_cap_kw`, the subscription moves to `ACTIVE`, `activated_at` is stamped from the logical clock, `committed_capacity_kw` grows by the allocation, and both the subscription's and the program's `version` increment. If capacity is insufficient, the outcome is not an error: the subscription parks, moving from `PENDING` to `WAITLISTED` with `waitlisted_at` stamped, and only the subscription's `version` increments.

Parked subscriptions are promoted by the waitlist promotion scan, which runs automatically after any capacity release — a subscription terminating from `ACTIVE` or `SUSPENDED`, or an amendment raising `capacity_cap_kw`. The scan computes the remaining capacity as `capacity_cap_kw` minus the summed `allocation_kw` of `ACTIVE` and `SUSPENDED` subscriptions, then walks the program's `WAITLISTED` subscriptions ordered by `waitlisted_at` ascending with `created_at` ascending as tie-break. A candidate whose `allocation_kw` fits within the remaining capacity at its turn moves to `ACTIVE`, with `activated_at` stamped, `waitlisted_at` cleared, and the remaining capacity reduced by its allocation. A candidate that does not fit stays `WAITLISTED` and the scan continues past it — skip-and-continue, with no head-of-line blocking — and `PENDING` subscriptions never auto-promote. Because the scan runs inside the request whose capacity release triggered it, the promoted subscriptions' `version` increments and the program's own further `version` increments are applied within that same request's response.

Suspension and termination round out the lifecycle. Suspending moves an `ACTIVE` subscription to `SUSPENDED`; a suspended subscription retains its capacity allocation — `committed_capacity_kw` is the summed `allocation_kw` over the program's `ACTIVE` and `SUSPENDED` subscriptions — so suspending leaves it unchanged, and its bills continue to accrue prorated days. Reinstatement returns a `SUSPENDED` subscription to `ACTIVE`, provided the program is still `OPEN`, else `ERR_PROGRAM_NOT_OPEN`. Termination is possible from `PENDING`, `WAITLISTED`, `ACTIVE`, or `SUSPENDED` and is always final: `terminated_at` is stamped, a waitlisted subscription's `waitlisted_at` is cleared, and a subscription terminating from `ACTIVE` or `SUSPENDED` releases its allocation — `committed_capacity_kw` falls by the `allocation_kw` — which in turn triggers the waitlist promotion scan on the program; both the subscription's and the program's `version` increment on a capacity-releasing termination. Any activation, suspension, reinstatement, or termination attempted from a state the transition does not allow is rejected with `ERR_SUBSCRIPTION_STATE_INVALID`.

### 3.6. Monthly Billing and the Two Credit Variants

Billing is monthly and subscription-scoped. A `ProgramManager` creates a bill by naming the `subscription_id`, the `period_month` in `YYYY-MM` form, the customer's actual `usage_kwh` for the period, and the customer's gross `charges_cents` for the period. The subscription must be `ACTIVE` or `SUSPENDED` — billing a `PENDING`, `WAITLISTED`, or `TERMINATED` subscription is rejected with `ERR_SUBSCRIPTION_STATE_INVALID` — and the `period_month` may not be later than the logical clock's month, else `ERR_FUTURE_PERIOD`. Both `usage_kwh` and `charges_cents` may be zero but never negative, else `ERR_QUANTITY_INVALID`. At most one non-`VOID` bill may exist for a given subscription and period month: a second one is rejected with `ERR_DUPLICATE_BILL`, a check applied after the future-period check and before the quantity-sanity check, so a duplicate month carrying a negative `usage_kwh` reports `ERR_DUPLICATE_BILL`. A new bill lands in `DRAFT` status with `issued_credit_cents`, the proration fields, and `issued_at` unset — but its `provisional_credit_cents` is computed immediately, at creation, per the PROVISIONAL variant below.

Both credit variants share the same skeleton. The deemed monthly generation of a subscription is its `allocation_kw` multiplied by the program's `kwh_per_kw_monthly`. The eligible energy is the smaller of a usage figure and that deemed amount, and the credit on the eligible energy is a marginal tier sum: walk the program's `rate_tiers` in ascending order of `up_to_kwh`, and let each tier contribute the number of eligible kilowatt-hours falling inside its band — the smaller of the remaining eligible energy and the tier's width, where the first tier's band starts at zero and a null `up_to_kwh` is unbounded — multiplied by that tier's `rate_cents_per_kwh`, in exact integer cents.

The PROVISIONAL variant runs at bill creation. Its usage figure is the subscription's declared `estimated_usage_kwh`; it applies no proration and no cap against charges, and its result is stored in `provisional_credit_cents`. The FINAL variant runs at issue and reissue. Its usage figure is the bill's actual `usage_kwh`; after the tier sum, the base credit is prorated by calendar days — the number of days of the `period_month` during which the subscription held `ACTIVE` or `SUSPENDED` status for any part of the day, derived from its `activated_at` and `terminated_at` against the period bounds, with a subscription active for the entire month scoring the full day count of the month. The proration divides the base credit by the calendar days in the period and multiplies by the active days, rounding half-up to a whole cent — the only division in billing — and the final credit is the smaller of the prorated amount and the bill's `charges_cents`. The result is stored in `issued_credit_cents`, alongside `proration_active_days` and `proration_days_in_period`.

Issuing a `DRAFT` bill moves it to `ISSUED`, computes the FINAL credit, records both proration fields, and stamps `issued_at`. A customer dispute moves an `ISSUED` bill to `DISPUTED`; a `reason` may accompany the request but is accepted for the audit trail only and is not persisted on the bill resource. Reissue brings a `DISPUTED` bill back to `ISSUED`: the request may carry corrected `usage_kwh` or `charges_cents`, which are applied before the FINAL credit is recomputed — either corrected value must be a non-negative integer, else `ERR_QUANTITY_INVALID` — and `issued_at` is refreshed to the logical clock. A bill in `DRAFT` or `DISPUTED` may be voided into the terminal `VOID` state. Any issue, dispute, reissue, or void attempted from a state the transition does not allow is rejected with `ERR_BILL_STATE_INVALID`.

### 3.7. Retirements and Double-Counting Prevention

Retirement is the act that takes a certificate out of circulation forever, and it always consumes a whole batch: the request names the `certificate_id` and a `purpose` of `VOLUNTARY_PROGRAM`, `COMPLIANCE`, or `WHOLESALE_CLAIM`, plus the purpose-specific linkage — `program_id` for `VOLUNTARY_PROGRAM`, `obligation_id` for `COMPLIANCE`, and `external_claim_reference` for `WHOLESALE_CLAIM`. The role must match the purpose per §2.1, the holder account must be in `ACTIVE` standing, else `ERR_ACCOUNT_NOT_ACTIVE` — a check applied before the certificate's own disposition is examined, so a locked certificate held by a suspended account reports `ERR_ACCOUNT_NOT_ACTIVE` — and the certificate must be `ACTIVE`: retiring a `LOCKED`, `RETIRED`, or `REVOKED` certificate is rejected with `ERR_CERTIFICATE_NOT_ACTIVE`.

Eligibility rules then gate the retirement, and they are evaluated in a fixed order: vintage first, then region, then technology, and the market-class gate last — for `VOLUNTARY_PROGRAM` the target program's `market_class` must be `VOLUNTARY`, else `ERR_MARKET_CLASS_MISMATCH`, and this check is applied after the vintage, region, and technology checks, so a certificate that also fails those rules reports the earlier failure. The vintage rule is a closed month window: counting the months between the certificate's `vintage_month` and the logical clock's month — twelve times the year difference plus the month difference — the count must be at least zero and at most one less than the program's `vintage_window_months`; with the default twelve-month window, a certificate is eligible from its vintage month through the eleventh month that follows it, and anything older is rejected with `ERR_VINTAGE_INELIGIBLE`. The certificate's `region_code` must be a member of the program's `eligible_region_codes`, else `ERR_REGION_INELIGIBLE`, and its `technology` a member of `eligible_technologies`, else `ERR_TECHNOLOGY_INELIGIBLE`. For `COMPLIANCE`, the target obligation must be `OPEN`, else `ERR_OBLIGATION_NOT_OPEN`; the vintage rule is a closed year window — the certificate's vintage year must be the obligation's `year` or one of the two years immediately preceding it, else `ERR_VINTAGE_INELIGIBLE` — and the certificate's `region_code` must equal the obligation's `region_code` exactly, else `ERR_REGION_INELIGIBLE`. For `WHOLESALE_CLAIM`, the `external_claim_reference` must be unique across all retirements ever recorded; a duplicate is rejected with `ERR_DUPLICATE_CLAIM_REFERENCE`.

A successful retirement moves the certificate from `ACTIVE` to the terminal `RETIRED` state and writes an immutable `Retirement` row that freezes the certificate's `quantity_mwh`, `vintage_month`, `region_code`, and `technology`, records the holder's `account_id` at retirement time, and starts with `claimed_in_report_id` unset. The holder's `active_holdings_mwh` falls by the retired quantity. For `VOLUNTARY_PROGRAM`, the program's `retired_mwh_current_year` — the summed `quantity_mwh` of the program's voluntary retirements whose `created_at` year equals the logical clock's year — is recomputed as the retirement lands. For `COMPLIANCE`, the obligation's `covered_mwh` grows by the retired quantity, and if coverage has reached or exceeded `required_mwh` — exact equality counts — the obligation flips from `OPEN` to `MET` in the same atomic mutation, its `version` incrementing exactly once for the whole request; this MET flip is evaluated only for obligations still `OPEN`, since compliance retirements against a non-`OPEN` obligation are refused above.

Double-counting is prevented at four independent layers. A certificate's terminal `RETIRED` status makes a second retirement of the same batch impossible. Wholesale claim references are unique registry-wide. A retirement claimed by an accepted report carries that report's id in `claimed_in_report_id`, so it can never be pinned into another accepted report — submissions that try are rejected with `ERR_DOUBLE_COUNT`. And only one `ACCEPTED` claim report may exist for a given scope target and `report_year`, enforced both at creation and again at submission with `ERR_DUPLICATE_REPORT`.

### 3.8. Compliance Obligations and the Annual Close

A `ComplianceOfficer` creates an annual obligation by naming the load-serving entity in `lse_name`, the compliance `year`, the `region_code` that certificates retired against it must carry, the positive `required_mwh`, and optionally a `penalty_rate_cents_per_mwh` that defaults to 5000 cents per megawatt-hour and, when supplied, must be a non-negative integer — a negative rate is rejected with `ERR_VALIDATION`. The obligation starts `OPEN` with `covered_mwh` at zero and `penalty_cents` unset; `covered_mwh` is a derived figure recomputed from recorded retirements on every read.

Coverage is a pure derivation: `covered_mwh` is the summed `quantity_mwh` over all compliance retirements pointing at this obligation, unfiltered by year, and the obligation is `MET` exactly when coverage is greater than or equal to `required_mwh`. Compliance retirements are accepted only while the obligation is `OPEN`, so once an obligation has flipped to `MET`, further compliance retirements against it are rejected with `ERR_OBLIGATION_NOT_OPEN` unless a true-up amendment reopens it.

True-up amendments let a `ComplianceOfficer` revise `required_mwh` or `penalty_rate_cents_per_mwh` while the obligation is `OPEN` or `MET`; amending a closed obligation is rejected with `ERR_OBLIGATION_NOT_OPEN`. The write is guarded by `expected_obligation_version` per §2.7. Its evaluation order is pinned: first coverage is frozen from the retirements already recorded, then the amendment is applied, then the obligation's state is re-derived — `MET` if coverage reaches the new requirement, otherwise `OPEN` — and only then is the result persisted. The amendment and any re-derivation are one atomic mutation, so the obligation's `version` increments exactly once for the whole request; in particular, amending a `MET` obligation's requirement above its current coverage flips it back to `OPEN` inside the same write.

The annual close is the `ComplianceOfficer`'s final act on an obligation, permitted from `OPEN` or `MET`. When coverage meets the requirement, the obligation closes as `CLOSED_MET` with `penalty_cents` set to zero. When coverage falls short, it closes as `CLOSED_SHORTFALL` and the penalty is exact integer arithmetic: the deficit in megawatt-hours — `required_mwh` minus `covered_mwh` — multiplied by the obligation's `penalty_rate_cents_per_mwh`, stored in `penalty_cents`. Closing an already closed obligation is rejected with `ERR_OBLIGATION_NOT_OPEN`, and both `CLOSED_MET` and `CLOSED_SHORTFALL` are terminal.

### 3.9. Annual Claim Reports

Claim reports aggregate a year's retirements into an auditable public claim. Report creation is scoped: a `scope` of `VOLUNTARY_PROGRAM` requires the `program_id` and a `ProgramManager` caller, while `COMPLIANCE_OBLIGATION` requires the `obligation_id` and a `ComplianceOfficer` caller; `report_year` selects the calendar year whose retirements the report aggregates. Creation pins the report's `retirement_ids`: the set of all retirements matching the scope — voluntary retirements of the named program, or compliance retirements of the named obligation — whose `created_at` year equals `report_year` and whose `claimed_in_report_id` is unset at pin time, listed in the retirements' creation order. From that pinned set the report derives `total_mwh` as the summed `quantity_mwh`, plus two bucket maps: `totals_by_technology` summing `quantity_mwh` per technology and `totals_by_region` summing it per `region_code`. A reconciliation invariant holds at all times: the bucket values of each map must sum exactly to `total_mwh`. A new report is `DRAFT`, with `submitted_by_user_id` and `rejection_reason` unset, and creation is refused with `ERR_DUPLICATE_REPORT` when an `ACCEPTED` report already exists for the same scope target and `report_year`.

Submission moves a report from `DRAFT` to `SUBMITTED` and re-checks the guards in safety-before-fiscal order: the report's own state first (`ERR_REPORT_STATE_INVALID` from any other state), then the role match per scope, then the double-count guard — no pinned retirement may carry a `claimed_in_report_id` set by another `ACCEPTED` report, else `ERR_DOUBLE_COUNT` — then the single-accepted-report rule is enforced again (`ERR_DUPLICATE_REPORT` when another `ACCEPTED` report already exists for the same scope target and `report_year`), then the pinned set must be non-empty, else `ERR_REPORT_EMPTY`, and finally, for the `VOLUNTARY_PROGRAM` scope, the recomputed `total_mwh` may not exceed the program's `annual_claim_cap_mwh`, else `ERR_CLAIM_CAP_EXCEEDED`. Submission records the caller in `submitted_by_user_id` and recomputes `total_mwh` and both bucket maps from the pinned set.

Adjudication belongs to the `Auditor` under segregation of duties. Accepting moves the report from `SUBMITTED` to the terminal `ACCEPTED` state and stamps every pinned retirement's `claimed_in_report_id` with this report's id — the moment that locks those retirements out of any future claim. Rejection moves it from `SUBMITTED` to `REJECTED` and records the supplied `reason` in `rejection_reason`; the `reason` may be omitted, leaving `rejection_reason` unset. Either decision by the same user who submitted the report is rejected with `ERR_SELF_APPROVAL`, and a submission, acceptance, rejection, or revision attempted from a state the transition does not allow is rejected with `ERR_REPORT_STATE_INVALID`.

Rejection is recoverable. Revising a `REJECTED` report returns it to `DRAFT` under the same scope-role match as submission, recomputes the pinned `retirement_ids` from scratch — dropping retirements claimed elsewhere since and picking up newly eligible ones — recomputes the totals, and clears both `rejection_reason` and `submitted_by_user_id`, readying the report for a fresh submission.

## 4. Endpoint Definitions

Operations that create a new resource — registering a generator, submitting a reading, creating an account, proposing a trade, creating a program, enrolling a subscription, creating a bill, recording a retirement, creating an obligation, or creating a claim report — return `201 Created`. Operations that modify an existing resource, including lifecycle transitions, configuration amendments, mint runs, settlements, and logical-clock moves, return `200 OK`. The table below is a summary only; request bodies, derived fields, and side effects are specified by the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/greenpower/generators` | Register a new generator (status `REGISTERED`) | RegistryAdmin |
| GET | `/greenpower/generators` | List generators with filters and pagination | All roles |
| GET | `/greenpower/generators/{id}` | Fetch one generator | All roles |
| PATCH | `/greenpower/generators/{id}` | Update generator configuration (OCC-guarded); region changes never retro-alter minted certificate snapshots | RegistryAdmin |
| POST | `/greenpower/generators/{id}/submit-verification` | `REGISTERED` or `REJECTED` → `VERIFICATION` | GeneratorOperator |
| POST | `/greenpower/generators/{id}/verify` | `VERIFICATION` → `ACTIVE`; auto-creates the generator's `GENERATOR` account | RegistryAdmin |
| POST | `/greenpower/generators/{id}/reject-verification` | `VERIFICATION` → `REJECTED` with reason | RegistryAdmin |
| POST | `/greenpower/generators/{id}/suspend` | `ACTIVE` → `SUSPENDED` | RegistryAdmin |
| POST | `/greenpower/generators/{id}/reinstate` | `SUSPENDED` → `ACTIVE` | RegistryAdmin |
| POST | `/greenpower/generators/{id}/decommission` | `ACTIVE` or `SUSPENDED` → `DECOMMISSIONED` (terminal) | RegistryAdmin |
| POST | `/greenpower/generators/{id}/mint-run` | Consume all `ACCEPTED`, unminted readings chronologically and mint certificates into the generator's account | RegistryAdmin |
| POST | `/greenpower/meter-readings` | Submit a meter reading for a generator (caller must be that generator) | GeneratorOperator |
| GET | `/greenpower/meter-readings` | List readings with filters | All roles |
| GET | `/greenpower/meter-readings/{id}` | Fetch one reading | All roles |
| POST | `/greenpower/meter-readings/{id}/attest` | `SUBMITTED` → `ATTESTED` (segregation of duties; 30-day window) | MeterAttester |
| POST | `/greenpower/meter-readings/{id}/reject` | `SUBMITTED` or `ATTESTED` → `REJECTED` | MeterAttester |
| POST | `/greenpower/meter-readings/{id}/resubmit` | `REJECTED` → `SUBMITTED` (revision cycle) | GeneratorOperator |
| POST | `/greenpower/meter-readings/{id}/accept` | `ATTESTED` → `ACCEPTED`; credits the generator's accepted total | RegistryAdmin |
| POST | `/greenpower/meter-readings/{id}/void` | `ACCEPTED` → `VOIDED` (only while unminted); debits the accepted total | RegistryAdmin |
| POST | `/greenpower/accounts` | Create a `BROKER` or `PROGRAM` account (`GENERATOR` accounts are auto-created at generator verify) | RegistryAdmin |
| GET | `/greenpower/accounts` | List accounts with filters | All roles |
| GET | `/greenpower/accounts/{id}` | Fetch one account (includes derived holdings) | All roles |
| POST | `/greenpower/accounts/{id}/suspend` | `ACTIVE` → `SUSPENDED`; cancels its `PROPOSED` trades | RegistryAdmin |
| POST | `/greenpower/accounts/{id}/reinstate` | `SUSPENDED` → `ACTIVE`; resets failure strikes to zero | RegistryAdmin |
| GET | `/greenpower/certificates` | List certificates with filters | All roles |
| GET | `/greenpower/certificates/{id}` | Fetch one certificate | All roles |
| POST | `/greenpower/certificates/{id}/revoke` | `ACTIVE` or `LOCKED` → `REVOKED`; cascades to fail `ACCEPTED` trades and strike the seller | RegistryAdmin |
| POST | `/greenpower/certificates/{id}/transfer` | Bilateral whole-batch transfer of an `ACTIVE` certificate to another account (no settlement, no split) | RegistryAdmin, BrokerTrader |
| POST | `/greenpower/trades` | Propose a broker trade over whole or partial certificate quantities (`PROPOSED`; no locks yet) | BrokerTrader |
| GET | `/greenpower/trades` | List trades with filters | All roles |
| GET | `/greenpower/trades/{id}` | Fetch one trade | All roles |
| POST | `/greenpower/trades/{id}/accept` | Buyer accepts: `PROPOSED` → `ACCEPTED`; locks all item certificates atomically; sets the five-day settlement deadline | BrokerTrader |
| POST | `/greenpower/trades/{id}/settle` | Buyer settles before the deadline: transfers or splits certificates and computes proceeds | BrokerTrader |
| POST | `/greenpower/trades/{id}/cancel` | Seller cancels a `PROPOSED` trade (no locks engaged) | BrokerTrader |
| POST | `/greenpower/trades/{id}/expire` | Registry expires an `ACCEPTED` trade past its deadline: unlocks certificates, strikes the buyer | RegistryAdmin |
| POST | `/greenpower/programs` | Create a green tariff program (`DRAFT`) | RegistryAdmin |
| GET | `/greenpower/programs` | List programs with filters | All roles |
| GET | `/greenpower/programs/{id}` | Fetch one program (includes `committed_capacity_kw`) | All roles |
| PATCH | `/greenpower/programs/{id}` | Amend program configuration (OCC-guarded); raising the capacity cap triggers the waitlist promotion scan | RegistryAdmin |
| POST | `/greenpower/programs/{id}/open` | `DRAFT` → `OPEN` (requires a wired holding account) | RegistryAdmin |
| POST | `/greenpower/programs/{id}/archive` | `OPEN` → `ARCHIVED` (requires no live subscriptions) | RegistryAdmin |
| POST | `/greenpower/subscriptions` | Enroll a customer (`PENDING`); OCC-guarded on the program version | ProgramManager |
| GET | `/greenpower/subscriptions` | List subscriptions with filters | All roles |
| GET | `/greenpower/subscriptions/{id}` | Fetch one subscription | All roles |
| POST | `/greenpower/subscriptions/{id}/activate` | `PENDING` → `ACTIVE` if capacity fits, else `PENDING` → `WAITLISTED` (not an error) | ProgramManager |
| POST | `/greenpower/subscriptions/{id}/suspend` | `ACTIVE` → `SUSPENDED` (retains the capacity allocation) | ProgramManager |
| POST | `/greenpower/subscriptions/{id}/reinstate` | `SUSPENDED` → `ACTIVE` | ProgramManager |
| POST | `/greenpower/subscriptions/{id}/terminate` | `PENDING`/`WAITLISTED`/`ACTIVE`/`SUSPENDED` → `TERMINATED`; releases capacity and triggers the waitlist promotion scan | ProgramManager |
| POST | `/greenpower/bills` | Create a monthly bill (`DRAFT`) with the provisional credit from estimated usage | ProgramManager |
| GET | `/greenpower/bills` | List bills with filters | All roles |
| GET | `/greenpower/bills/{id}` | Fetch one bill | All roles |
| POST | `/greenpower/bills/{id}/issue` | `DRAFT` → `ISSUED`; computes the final credit (actual usage, proration, charges cap) | ProgramManager |
| POST | `/greenpower/bills/{id}/dispute` | `ISSUED` → `DISPUTED` | ProgramManager |
| POST | `/greenpower/bills/{id}/reissue` | `DISPUTED` → `ISSUED` with optional corrected usage or charges; recomputes the final credit | ProgramManager |
| POST | `/greenpower/bills/{id}/void` | `DRAFT` or `DISPUTED` → `VOID` (terminal) | ProgramManager |
| POST | `/greenpower/retirements` | Retire a whole `ACTIVE` certificate for a purpose | ProgramManager, ComplianceOfficer, BrokerTrader |
| GET | `/greenpower/retirements` | List retirements with filters | All roles |
| GET | `/greenpower/retirements/{id}` | Fetch one retirement | All roles |
| POST | `/greenpower/compliance-obligations` | Create an annual obligation (`OPEN`) | ComplianceOfficer |
| GET | `/greenpower/compliance-obligations` | List obligations with filters | All roles |
| GET | `/greenpower/compliance-obligations/{id}` | Fetch one obligation | All roles |
| PATCH | `/greenpower/compliance-obligations/{id}` | True-up amendment of the requirement or penalty rate (OCC-guarded); may flip `MET` → `OPEN` | ComplianceOfficer |
| POST | `/greenpower/compliance-obligations/{id}/close` | Annual close: covered → `CLOSED_MET` (penalty zero); deficit → `CLOSED_SHORTFALL` with penalty | ComplianceOfficer |
| POST | `/greenpower/claim-reports` | Create a `DRAFT` annual claim report; pins the current unclaimed retirement set for its scope and year | ProgramManager, ComplianceOfficer |
| GET | `/greenpower/claim-reports` | List claim reports with filters | All roles |
| GET | `/greenpower/claim-reports/{id}` | Fetch one claim report | All roles |
| POST | `/greenpower/claim-reports/{id}/submit` | `DRAFT` → `SUBMITTED`; enforces the double-count guard before the claim cap (safety before fiscal) | ProgramManager, ComplianceOfficer |
| POST | `/greenpower/claim-reports/{id}/accept` | `SUBMITTED` → `ACCEPTED` by the auditor (segregation of duties); marks pinned retirements claimed | Auditor |
| POST | `/greenpower/claim-reports/{id}/reject` | `SUBMITTED` → `REJECTED` by the auditor with reason | Auditor |
| POST | `/greenpower/claim-reports/{id}/revise` | `REJECTED` → `DRAFT`; recomputes the pinned retirement set from scratch | ProgramManager, ComplianceOfficer |
| POST | `/greenpower/_clock/set_current_utc` | Move the logical clock to a supplied ISO 8601 UTC instant | RegistryAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_GENERATOR_NOT_ACTIVE` | 409 |
| `ERR_INVALID_GENERATOR_STATE` | 409 |
| `ERR_INVALID_READING_STATE` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_CERTIFICATE_NOT_ACTIVE` | 409 |
| `ERR_TRADE_STATE_INVALID` | 409 |
| `ERR_PROGRAM_NOT_OPEN` | 409 |
| `ERR_SUBSCRIPTION_STATE_INVALID` | 409 |
| `ERR_BILL_STATE_INVALID` | 409 |
| `ERR_OBLIGATION_NOT_OPEN` | 409 |
| `ERR_REPORT_STATE_INVALID` | 409 |
| `ERR_SELF_ATTESTATION` | 403 |
| `ERR_SELF_APPROVAL` | 403 |
| `ERR_DOUBLE_COUNT` | 422 |
| `ERR_PERIOD_INVERTED` | 400 |
| `ERR_FUTURE_PERIOD` | 422 |
| `ERR_READING_PERIOD_OVERLAP` | 409 |
| `ERR_ATTESTATION_WINDOW_EXPIRED` | 422 |
| `ERR_SETTLEMENT_WINDOW_EXPIRED` | 422 |
| `ERR_TRADE_NOT_EXPIRED` | 409 |
| `ERR_VINTAGE_INELIGIBLE` | 422 |
| `ERR_REGION_INELIGIBLE` | 422 |
| `ERR_TECHNOLOGY_INELIGIBLE` | 422 |
| `ERR_DUPLICATE_CLAIM_REFERENCE` | 409 |
| `ERR_DUPLICATE_BILL` | 409 |
| `ERR_DUPLICATE_UTILITY_ACCOUNT` | 409 |
| `ERR_DUPLICATE_REPORT` | 409 |
| `ERR_QUANTITY_INVALID` | 400 |
| `ERR_MARKET_CLASS_MISMATCH` | 422 |
| `ERR_REPORT_EMPTY` | 422 |
| `ERR_ALLOCATION_EXCEEDS_CAP` | 422 |
| `ERR_CLAIM_CAP_EXCEEDED` | 422 |
| `ERR_READING_ALREADY_MINTED` | 409 |
| `ERR_PROGRAM_HAS_ACTIVE_SUBSCRIPTIONS` | 409 |
| `ERR_PROGRAM_HOLDING_ACCOUNT_MISSING` | 422 |
