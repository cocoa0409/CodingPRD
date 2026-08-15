# Worklog — task_1691_renewable_energy_certificate_green_tariff

## Step 1: Create Task Directory — 2026-08-14T08:22:00.000Z

Task directory `tasks/task_1691_renewable_energy_certificate_green_tariff/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T09:34:48.663Z

Done. All three scaffold artifacts are generated, lint-clean, and self-consistent.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/SCAFFOLD.yaml` (§1.0–§1.7 only — no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

## Counts
- **SCAFFOLD**: 11 entities, 10 state machines, 4 OCC concurrency rules, 9 calculations, 40 validations (priority-ordered), 71 endpoints (incl. `POST /greenpower/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default), 40 error codes, 7 roles
- **Difficulty design**: 25 instances across all 9 rules (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear_state_machine 4, transitive_cascade 2, priority_pair_conflict 3, boundary_precision 3, cross_entity_state_dependency 4, resource_temporal_overlap 2, compensating_invariant 2)
- **Corner design**: 62 instances (58 active recipes + 4 `excluded_because` stubs) across all 9 taxonomy sections
- **Lint**: `VERDICT: clean lint` (945 calls scanned; zero violations; all FKs reverse-reachable)

## Harder-than-expert mechanics designed in
- **Depth-5 transitive cascade**: certificate revoke → ACCEPTED trade FAILED → seller strike +1 → account SUSPENDED at threshold 3 → seller's unrelated PROPOSED trades CANCELLED; plus depth-3 terminate → capacity release → waitlist promotion cascade
- **Multi-bucket chronological minting** with kWh carryover, calendar-year carryover reset, per-generator serial spaces, and serial-range split partitioning with conservation invariants
- **Dual-variant calculations in two domains**: bill credit (PROVISIONAL 4600 vs FINAL 6000, with calendar-day proration `round_half_up(6000×16/31)=3097`) and trade settlement (GROSS 90369/90000 vs NET 90000/89631, per-line fee rounding pinned at 369 vs the naive 315)
- **Two segregation-of-duties gates** (self-attestation, self-approval) plus entity-backed ownership for GeneratorOperator/BrokerTrader
- **Four OCC rules** (subscription create, generator PATCH, program PATCH, obligation PATCH) with cascade-induced version drift tested via stale-version 412s
- **Boundary arithmetic**: exact-1000-kWh mint, exact capacity fit (600+400==1000 admits, +1 waitlists), fee-tier 99/100 MWh edge with half-up `.5` rounding, vintage window month-11-in/month-12-out, inclusive settlement/attestation deadlines, strike threshold inclusive at 3
- **Validation priority conflicts** across three distinct category pairs (state>temporal, safety>fiscal, existence>state) with dual-failure recipes
- Claim-report version-pinning with double-count guard, REJECTED→DRAFT amendment cycle, and bucket-reconciliation invariant

All numeric assertions in recipes were pre-computed as literals; every `${var}` is bound by an earlier `captures:`; all clock-dependent setups use the declared clock endpoint.

## Step 3: Copy Shared Files — 2026-08-14T09:35:19.821Z

Copied `./INSTRUCTION.md` → `tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T09:57:24.736Z

All contracts verified. The PRD is complete.

## Summary

**Output file written:** `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/PRD.md` — 377 lines.

**Section coverage:**
- **§1 Introduction** — 3 paragraphs (business trust context, dual voluntary/compliance market model, `/greenpower` mount + logical-clock determinism).
- **§2 Global Specifications** — 9 subsections: §2.1 RBAC (7 roles, header contract, entity-backed vs opaque identity prose for every role, purpose/scope/ownership match rules), §2.2 response envelope (emitted byte-verbatim from `section-2.2-response-structure.md`, confirmed), §2.3 pagination (limit 10/1–100, offset 0, `created_at` ascending, all 11 list-endpoint filter sets enumerated), §2.4 logical clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), §2.5 common properties (UUID `id`, 3-fractional-digit timestamps, `version`; explicit `Retirement` exception — only `id`+`created_at`, immutable), §2.6 integer arithmetic + round-half-up at the two pinned division points, §2.7 OCC (all 4 rules with named `expected_*_version` fields → `ERR_STALE_VERSION`/412), §2.8 validation pipeline (all 12 ordered stages + notable within-stage orderings), §2.9 serial namespaces/snapshots/conservation.
- **§3 Business Logic** — 9 subsections covering all 11 entities: generator lifecycle, meter-reading attestation cycle, minting/carryover algorithm, accounts+trades+settlement+splits+revocation cascades+transfer, programs+subscriptions+waitlist scan, billing (PROVISIONAL/FINAL variants), retirements+eligibility+double-count layers, obligations+true-up+close, claim reports.
- **§4 Endpoints** — 71-row table (4 columns), mechanically verified equal to the scaffold's endpoint set; 201/200 status rules stated.
- **§5 Error Catalogue** — 40-row table (2 columns), mechanically verified equal to the scaffold's error set; no trigger conditions.

**Hard Contract results:**
- **Contract 1 (Field-Name Coverage):** 101 required identifiers (entity fields + endpoint inputs + query params + response-only names), 0 missing — PASS.
- **Contract 3 (§3 Path Purity):** 659 backtick tokens in §3, 0 paths / 0 bare methods / 0 method+path combos — PASS.
- All 40 error IDs appear in §1–§4 prose; all state values, enum values, and role names present; no fuzzy/approximating words or operator syntax detected; §2.2 byte-verbatim; document ends at §5 with no audit footer.

**Zero-Silence Rule self-audit (every scaffold behavior pinned in prose):**
- entities (11/11, all fields with defaults/snapshots/computed semantics): **yes**
- state_machines (10/10 machines, every from→to transition with preconditions paired to error IDs and all side effects incl. cascades — account-suspension trade cancellation, revoke→FAILED strike cascade, waitlist promotion on termination/cap-raise, atomic single-bump OPEN→MET and MET→OPEN): **yes**
- calculations (9/9 — mint carryover with year-boundary discard, dual bill-credit variants with proration order, per-line fee rounding pinned before summation with the non-conformant-aggregate warning, waitlist waterfall skip-and-continue, coverage threshold inclusivity + PATCH evaluation order, vintage windows month/year granularity, claim totalization reconciliation invariant, shortfall penalty, serial split partition): **yes**
- validations (39/39 — global priority pipeline stated with relative-ordering prose, per-endpoint applies_to scopes enumerated, safety-before-fiscal ordering on report submit): **yes**
- concurrency_rules (4/4 — write capability + OCC field + `ERR_STALE_VERSION`/412, stale-version framing only): **yes**
- endpoints (71/71 side effects narrated; clock endpoint included): **yes**
- errors (40/40 trigger conditions in §2/§3 prose): **yes**
- roles (7/7 with identity translation): **yes**

One judgment call to flag: the scaffold's validation 14 (obligation must be `OPEN` for PATCH amendment) literally conflicts with the `MET → OPEN` transition (triggered by that same PATCH). The PRD resolves this as: amendments permitted while `OPEN` or `MET` (the amendment can flip `MET` back to `OPEN`); compliance retirements strictly require `OPEN`; anything against `CLOSED_*` is rejected with `ERR_OBLIGATION_NOT_OPEN` — the only reading under which both scaffold entries remain reachable.

## Step 5: Generate Unit Tests — 2026-08-14T10:30:00.000Z

Generation complete and verified. Summary:

## Files written

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/test_helpers/`):
- `types.py` — 16 status/role enums + 11 entity TypedDicts; `Retirement` omits `updated_at`/`version` (append-only)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~60 methods, incl. `_clock/set_current_utc`)
- `api_errors.py` — all 38 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (incl. Retirement absence-of-version check, certificate serial contiguity invariant, claim-report bucket reconciliation invariant)
- `factories.py`, `constants.py` (1000 kWh/REC, 30-day attestation, 5-day settlement, strike limit 3, fee bps tiers, startup clock)
- `test_users.py` — shared constants for opaque roles + `make_generator_operator_headers`/`make_broker_trader_headers` entity-backed builders
- `fixtures.py` — composite chains: active generator, accepted reading, minted generator (per-reading clock control), broker pair with certificates, wire-and-open program, active subscription, trade lifecycle, retire/report helpers with scope-role-matched headers

**`test_suite/`**: `conftest.py` + 8 test files (registry basics, meter-reading pipeline, minting/serials, trade settlement/splits, account cascades, programs/capacity, billing variants, retirements/obligations/claims).

## Test counts

- **Total: 109 tests** (pytest-collected, all import-clean)
- **Queue A (Difficulty): 50 tests = 25 instances × 2, 0 skipped** — every instance passed the PRD two-condition filter
- **Queue B (Corner): 59 tests over 58 non-stub instances, 0 PRD-skipped** — one instance (`generator_verify_auto_creates_generator_account`) has 2 tests. The 4 `excluded_because` stubs (`error_double_count`, `error_reading_period_overlap`, `error_vintage_ineligible`, `error_generator_not_active`) were not translated; their difficulty-instance cross-references all resolve.

## Verification results

- All files `py_compile` clean; all 8 test modules import; `pytest --collect-only` yields exactly 109 tests (no stray collectable helpers)
- Every test has exactly one `Design:` tag; every tag resolves to a real instance name; no untagged/double-tagged tests
- Citation pass: every docstring's quoted PRD text survives whitespace-normalized literal match against `PRD.md` (0 unmatched fragments); no scaffold references; no skip/xfail markers

## Notable adjudications (no skips, but recipe repairs)

1. `waitlist_skip_and_continue_selector` — the recipe's numbers (cap 100, A=60, W2=40) are unreachable under the PRD (W2 would activate outright at 60+40=100 ≤ 100). Setup repaired with an extra always-ACTIVE 40-kW filler so both candidates genuinely park; the asserted skip-and-continue rule is preserved verbatim.
2. `quantity_invalid_zero_and_over` — the recipe's zero-kWh reading overlapped an ACCEPTED reading, which would fire the higher-priority overlap error; moved to a non-overlapping June period so `ERR_QUANTITY_INVALID` is the only applicable failure.
3. `generator_create_applies_defaults` — asserts all PRD §3.1-verbatim defaults exactly; `version == 1` and `created_at == updated_at` are not PRD-pinned, so the test asserts version presence/type instead (no literal guess).

## Step 6: Generate Implementation — 2026-08-14T10:30:00.000Z

Implementation complete for task_1691 (Renewable Energy Certificate & Green Tariff Administration). All work is in `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/implementation/`.

## Files written
- `start.sh` — executable; guards the pip install behind `python3 -c "import flask"` (no-op on per-test reboots), `exec python3 app.py` in the foreground, `$PORT` (default 10000), `0.0.0.0`
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry point, blueprint registration, envelope-wrapped error handlers (400/404/405/500)
- `errors.py` — ApiError + all 39 error IDs with their exact HTTP statuses
- `store.py` — in-memory dicts per entity, logical clock (boots at exactly `2026-08-01T00:00:00Z`), insertion-sequence counter
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`), auth (`X-User-ID`/`X-User-Role`, 7 roles), pagination (limit default 10, clamped 1–100; offset default 0), body/type/enum/ISO-8601 validators
- `services.py` — derived fields (holdings, cumulative kWh, committed capacity, covered MWh, retired-this-year), cascades (strike→auto-suspend→PROPOSED-trade cancel, waitlist promotion scan with skip-and-continue), calculators (marginal tier sum, half-up division, fee tiers, proration day counter, claim pinning/totalization)
- `routes/` — 12 modules: generators (incl. mint-run), readings, accounts, certificates, trades, programs, subscriptions, bills, retirements, obligations, reports, clock

## Coverage
- **71 endpoints**, every route in the SCAFFOLD endpoint table including `POST /greenpower/_clock/set_current_utc`
- **All 11 entities** with the specified system/computed fields; Retirement correctly omits `updated_at`/`version`
- **All 10 state machines** with preconditions and side effects, including cascades: verify→auto-create GENERATOR account; revoke-LOCKED→trade FAILED→seller strike→3-strike suspension→PROPOSED-trade cancellation; terminate/cap-raise→waitlist scan; compliance retirement→atomic covered+OPEN→MET single version bump
- **All 9 calculations**: mint carryover with calendar-year boundary discard (tracks carryover year internally), PROVISIONAL/FINAL bill credits with day-granularity proration and charges cap, per-line fee rounding before summation (GROSS/NET), serial split partition, waitlist scan, coverage threshold, vintage windows, claim totalization, shortfall penalty
- **Validation pipeline** in the scaffold's priority order (auth → role/ownership → schema → existence → OCC → state checks by priority number → SoD → double-count → temporal → eligibility/uniqueness → fiscal caps → referential guards), with PRD-observed orderings (account standing before trade state; vintage→region→technology; double-count before empty/cap)

## Verification
Four smoke suites (~150 assertions) run against fresh `start.sh` boots all pass, covering every entity lifecycle, both settlement modes, serial splits, year-boundary carryover, eligibility ordering, double-count, claim caps, OCC 412s on all four guarded writes, skip-and-continue waitlist promotion, and mid-month proration. Testing surfaced and fixed one real bug (waitlist promotions weren't stamping the parsed activation datetime used by proration). Same-port kill-and-restart confirmed: state fully wipes (`total_count: 0` after reboot). No seeding, no disk persistence, no reading of test_suite/test_helpers/difficulty files or sibling tasks.

## Step 7: Run Tests and Iterate — 2026-08-14T11:01:57.780Z

## Summary

**Result: all 8 parallel rounds green — 109/109 passed in every round (sweep 2).**

- **Iterations run**: 2 sweeps (8 rounds each). Sweep 1: 99/109 in every round, same 10 tests failing deterministically in 8/8 rounds. Sweep 2 (after fixes): 8× 109/109.

- **Tests deleted**: none. Both failures were test-side defects on rules the PRD covers verbatim; no PRD-silence or unique-derivability collapses found.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/test_suite/test_04_trade_settlement_and_serial_splits.py` — added `settle_accepted_trade` to the explicit `from test_helpers import (...)` list. Nine tests (all the GROSS/NET settlement, per-line fee rounding, fee-tier boundary, full/partial settle, and lock/expire round-trip tests) used this fixtures.py helper but never imported it, dying with `NameError` before any assertion ran. The helper itself is PRD-consistent, so once imported all 9 passed against the unmodified implementation.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/test_suite/test_03_minting_and_serial_namespaces.py::test_immediate_consistency_after_mint` — assertion mis-translated PRD §3.3 ("`minted_count` batches created, `total_minted_mwh` whole RECs issued"). The test asserted `minted_count == 2` for a 2500-kWh single-bucket mint, while its own later assertions (`len(certs) == 1`, `quantity_mwh == 2`) correctly describe the single 2-MWh batch the PRD mandates. Corrected to `minted_count == 1` and `total_minted_mwh == 2` (the latter also PRD-verbatim).

- **Fixes applied to `test_helpers/`**: none needed — fixtures, factories, role-header builders, and assertion library all construct PRD-consistent preconditions (verified by audit of all 9 helper files during the loop).

- **Fixes applied to `implementation/`**: none. The implementation (Flask, in-memory stores only, logical clock booting at `2026-08-01T00:00:00Z`, all 71 endpoints) was already PRD-faithful on every rule the 109 tests exercise.

- **Note**: sweep 2's first attempt was killed mid-run by a transient environmental kill (exit 144; host busy with concurrent pipelines) with zero test failures recorded up to that point; the rerun completed cleanly.

## Step 8: Finalize PRD — 2026-08-14T11:04:43.576Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/PRD_FINALIZED.md` exists as a byte-identical copy of PRD.md — **zero edits were made**, and each step_7_diff item was individually verified to require no PRD change.

**Line counts / %-delta**
- PRD.md: 376 lines; PRD_FINALIZED.md: 376 lines; delta 0.0%.

**Changes made:** none.

**Per-item justification (why each step_7_diff item required no PRD change):**

1. **`test_suite/test_04_trade_settlement_and_serial_splits.py` — added missing `settle_accepted_trade` import.**
   Pure test-side import defect (NameError before any assertion). No behavioral rule involved; the helper itself is PRD-consistent. I additionally verified the rules the 9 affected tests exercise are fully pinned by the PRD and matched by the implementation, so no silence hides behind this fix:
   - (a) Subject: GROSS/NET settlement money math, per-line fee rounding, fee-tier boundaries, settle deadline, lock/expire round-trips.
   - (b) Paths enumerated/read: `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/implementation/routes/trades.py` (propose/accept/settle/expire, lines 49, 86, 150-224 — deadline check `clock_now() > settlement_deadline`, per-line `round_half_up_div(line_cents * broker_fee_bps(t), 10000)` summed before assignment, GROSS/NET branches), `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/implementation/services.py` lines 150-162 (`round_half_up_div` with `ROUND_HALF_UP`; `broker_fee_bps` tiers `<100→50, <1000→35, >=1000→20`).
   - (c) No wording change — PRD lines 191, 193 (and §2.4 line 109) already specify all of this verbatim, including the tier boundaries, half-up-per-line-before-summation order, GROSS/NET formulas, and "at or before the deadline" window. Implementation matches; tests passed unmodified.

2. **`test_03_minting_and_serial_namespaces.py::test_immediate_consistency_after_mint` — corrected `minted_count` assertion from 2 to 1.**
   Test-side mis-translation of PRD §3.3, not a PRD silence.
   - (a) Subject: mint-run summary semantics (`minted_count`, `total_minted_mwh`, `carryover_kwh`, `certificate_ids`) for a 2500-kWh single-bucket mint.
   - (b) Paths enumerated/read: `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/implementation/routes/generators.py` lines 197-284 (`mint_run`: vintage bucketing by `period_start` month, carryover year-boundary discard, `whole = pool // 1000`, one certificate per bucket, response `minted_count: len(certificate_ids)`, `total_minted_mwh: total_minted`); the corrected test file lines 46-50, 79, 125, 157, 175-192 (all assertions now describe PRD-pinned behavior).
   - (c) No wording change — PRD line 179 already states verbatim: "`minted_count` batches created, `total_minted_mwh` whole RECs issued", and PRD lines 175-177 pin bucketing, whole-REC floor, and carryover. For 2500 kWh in one bucket the impl mints one batch of 2 MWh (`minted_count == 1`, `total_minted_mwh == 2`), exactly what the PRD mandates; the old test assertion contradicted the PRD, not the implementation.

The step_7_diff itself concurs: "no PRD-silence or unique-derivability collapses found," no implementation fixes, no test deletions. A fresh implementer reading PRD.md (= PRD_FINALIZED.md) already has every rule needed to reproduce the implementation on all 109 tested behaviors.

## Step 9: Complete PRD — 2026-08-14T11:11:08.515Z

PRD_COMPLETED.md is produced. Summary below.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (376 lines / 66,475 chars) → `workspace/PRD_COMPLETED.md` (376 lines / 71,767 chars). Char-delta: +5,292. Line count unchanged (all edits are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** ambiguity-pins: 27 · mismatch-revisions: 3 (the committed-capacity definition required three coordinated edits — activation rule, waitlist-scan rule, and the suspension paragraph — counted as one revision at three sites; §3.6 duplicate-bill ordering is also a light revision of a listed-order sentence).

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — pin `limit`/`offset` clamping: non-integer → `ERR_VALIDATION`; out-of-range integers clamped to [1,100] / ≥0 rather than rejected — implementation/util.py:79-103
- §2.4 — insert — ambiguity — clock move is bidirectional (no monotonicity rule) and `current_utc` echoes the request's `to_iso8601` string verbatim — implementation/routes/clock.py:19
- §2.5 — revise — mismatch — retirement immutability qualified: report accept stamps `claimed_in_report_id` onto retirements without adding `updated_at`/`version`; retirements carry "only `id` and `created_at` **of the common fields**" — implementation/routes/reports.py:150-153
- §2.7 — no change — (verified: enrollment does bump program version; PRD already pinned)
- §3.1 — insert — ambiguity — duplicate `facility_code` → `ERR_VALIDATION` (400); `cumulative_accepted_kwh` is derived at read time — implementation/routes/generators.py:37-39, 18-21
- §3.1 — insert — ambiguity — auto-created generator account starts with `failure_strikes` zero — implementation/routes/generators.py:156-168
- §3.1 — insert — ambiguity — generator config amendment allowed in any state, `DECOMMISSIONED` included — implementation/routes/generators.py:97-118
- §3.2 — insert — ambiguity — `metered_kwh` quantity check applied after the three period rules (overlap beats quantity error) — implementation/routes/readings.py:53-62
- §3.2 — insert — ambiguity — attestation window evaluated after the self-attestation duty check; rejection is not time-boxed; reject `reason` optional (may leave `rejection_reason` unset) — implementation/routes/readings.py:111-142
- §3.2 — insert — ambiguity — reading-acceptance checks reading state before generator standing (non-ATTESTED + suspended generator → `ERR_INVALID_READING_STATE`) — implementation/routes/readings.py:165-170
- §3.2 — insert — ambiguity — void `reason`, when supplied, is stored into the reading's `rejection_reason`; when omitted the field is left as-is — implementation/routes/readings.py:187-190
- §3.3 — insert — ambiguity — mint run with zero qualifying readings returns a zero summary with unchanged `carryover_kwh` and does not touch the generator — implementation/routes/generators.py:212-218
- §3.3 — insert — ambiguity — each reading marking (`minted`/`minted_vintage_month`) increments the reading's `version` and refreshes `updated_at`; stored carry is tagged with its producing year — implementation/routes/generators.py:267-273
- §3.4 — insert — ambiguity — account creation: `GENERATOR` type rejected with `ERR_VALIDATION`; `program_id` mandatory for `PROGRAM` accounts; supplied `generator_id`/`program_id` resolved for existence (`ERR_NOT_FOUND`); holdings recomputed per read; accounts begin with `failure_strikes` 0 — implementation/routes/accounts.py:28-54
- §3.4 — insert — ambiguity — `items` must be non-empty and each line's `quantity_mwh` an integer, else `ERR_VALIDATION` — implementation/routes/trades.py:36-48
- §3.4 — insert — ambiguity — trade-acceptance check order pinned: certificate re-qualification (`ERR_CERTIFICATE_NOT_ACTIVE`) precedes the `PROPOSED` state check — implementation/routes/trades.py:124-133
- §3.4 — insert — ambiguity — certificate transfer: receiving-account standing checked before certificate disposition — implementation/routes/certificates.py:95-99
- §3.5 — insert — ambiguity — program creation: `eligible_technologies` entries must be declared technologies; non-null `holding_account_id` must exist; `up_to_kwh` null-or-positive-int, `rate_cents_per_kwh` non-negative int; `vintage_window_months`/`kwh_per_kw_monthly` positive when supplied; derived figures recomputed per read — implementation/routes/programs.py:27-90
- §3.5 — insert — ambiguity — program amendment allowed in any state incl. `ARCHIVED`; `holding_account_id` may be amended to null — implementation/routes/programs.py:164-169
- §3.5 — insert — ambiguity — subscription enrollment check order pinned: OPEN → duplicate-account → quantity → market class → capacity ceiling — implementation/routes/subscriptions.py:37-52
- §3.5 — revise — mismatch — `committed_capacity_kw` is the summed `allocation_kw` over `ACTIVE` **and `SUSPENDED`** subscriptions (fixed at three sites: activation rule, waitlist scan, suspension paragraph) — implementation/services.py:33-40
- §3.5 — insert — ambiguity — waitlist promotion scan effects (promoted subscriptions' version bumps, program version bumps) land inside the triggering request — implementation/routes/subscriptions.py:167-172, services.py:104-112
- §3.6 — revise — ambiguity/order — bill creation: duplicate-bill check applied after future-period and before quantity sanity — implementation/routes/bills.py:40-47
- §3.6 — insert — ambiguity — dispute `reason` accepted but not persisted on the bill; reissue corrected `usage_kwh`/`charges_cents` must be non-negative integers — implementation/routes/bills.py:122, 136-145
- §3.7 — revise — ambiguity — retirement gate order pinned: holder-account standing before certificate disposition; market-class gate moved to after vintage/region/technology — implementation/routes/retirements.py:63-68, 107-109
- §3.7 — insert — ambiguity — MET flip evaluated only for `OPEN` obligations (others are refused earlier) — implementation/routes/retirements.py:69-71, 136-138
- §3.8 — insert — ambiguity — supplied `penalty_rate_cents_per_mwh` must be a non-negative integer (negative → `ERR_VALIDATION`); `covered_mwh` derived per read — implementation/routes/obligations.py:35-38, 18-21
- §3.9 — insert — ambiguity — pinned `retirement_ids` listed in retirement creation order — implementation/services.py:231
- §3.9 — revise — ambiguity — submission guard order pinned with the duplicate-report re-check placed between the double-count guard and the empty-report check — implementation/routes/reports.py:108-125
- §3.9 — insert — ambiguity — report-rejection `reason` is optional (may leave `rejection_reason` unset) — implementation/routes/reports.py:169-170

No remaining PRD silence or mismatch versus `implementation/` was found in the walk: endpoint table, error catalogue, state machines, mint/settlement/credit formulas, OCC guards, serial namespace rules, and list filters all match as written. Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1691_renewable_energy_certificate_green_tariff/workspace/PRD_COMPLETED.md`.

## Step 8/9: Test-and-fix diagnostic loop — 2026-08-14T11:15:00.000Z

8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 109 tests/round).

- **Iteration 1**: 99/109 passed in every round; union of failures = 10 tests, all deterministic (8/8 rounds each).
  - `test_04_trade_settlement_and_serial_splits.py` (9 tests): `NameError: settle_accepted_trade` — used but missing from the file's explicit `test_helpers` import list. Test-suite import bug; fixed by adding it to the import block.
  - `test_03_minting_and_serial_namespaces.py::test_immediate_consistency_after_mint`: asserted `minted_count == 2` for a 2500-kWh single-bucket run, contradicting PRD §3.3 ("`minted_count` batches created" — one batch of 2 RECs; the test itself asserts `len(certs) == 1`). Assertion corrected to `minted_count == 1` + `total_minted_mwh == 2`.
- **Iteration 2**: all 8 rounds 109/109 — SWEEP GREEN. No tests deleted, no implementation changes needed.
