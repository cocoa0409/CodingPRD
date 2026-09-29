# Worklog — task_2219_merchant_underwriting_portfolio_risk_monitoring

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2219_merchant_underwriting_portfolio_risk_monitoring/` and `tasks/task_2219_merchant_underwriting_portfolio_risk_monitoring/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T06:42:14.282Z

Scaffold generation for scenario 2219 is complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_2219_merchant_underwriting_portfolio_risk_monitoring/` and `scaffold_lint.py` reports `VERDICT: clean lint`.

## `SCAFFOLD.yaml` (§1.0–§1.7, 3181 lines)
Scenario text stored verbatim; `domain_name: merchant-underwriting-portfolio-risk`, `api_prefix: ""`, `difficulty_level: expert_plus`. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.

| Section | Count |
|---|---|
| §1.1 entities | 15 |
| §1.2 state machines | 9 (cyclic shape) |
| §1.2.1 OCC rules | 2 (`MerchantApplication`, `ReserveAccount`) |
| §1.3 calculations | 7 (2 dual-variant) |
| §1.4 validations | 53, priority-ordered 1→53 |
| §1.5 endpoints | 63 |
| §1.6 errors | 53 |
| §1.7 roles | 6 (`segregation_of_duties`) |

Complexity profile: primary `compliance_audit` / secondary `ledger_reconciliation`; layers `rate_threshold_triggers`, `cascading_side_effects`, `dual_variant_calculation`, `optimistic_concurrency`; topology `flat`; consistency `immediate`.

## `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
9 rule blocks / **20 instances** — variant divergence, four-additive-uplift clamp, per-day-line rounding order, frozen adequacy tier, parallel state dimensions, four- and five-link cascades, priority conflicts (funding-state vs fiscal, sanctions vs coverage, cooling vs amount), threshold/interval boundaries, and two ledger-conservation instances.

## `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)
**105 instances** across the nine mandated sections — 83 with full `test_recipe` blocks (1548 lint-verified API calls total across §1.8+§1.9) and 22 `excluded_because` stubs, each citing an existing §1.8 instance by name:

entities 13 · state_machines 20 (16+4) · calculations 20 (11+9) · validations 18 (12+6) · endpoints 15 (14+1) · errors 9 · rbac 5 · cross-cutting complexity layers 4 (2+2) · consistency model 1.

Audit results: **all 63 §1.5 endpoints** are exercised by at least one instance, and **all 53 error ids** are triggered. Field names, enum literals and defaults in every assert were machine-checked against §1.1/§1.5 (this caught and fixed `CLEAR`→`CLEARED`, `outcome: UPHELD`→`UPHOLD`, and `loss_offset_cents`→`loss_offset_from_settlement_cents`).

Fixes applied to SCAFFOLD.yaml during §1.9's §1.5 audit pass: validation priority 23 + `ERR_PROGRAM_STATE_INVALID` extended to declare the termination-execute guard (no remediation program in DRAFT/ACTIVE), and three `evaluate-month` transition actors corrected from `PortfolioController` to `RiskAnalyst` to match §1.5/§1.7.

## Step 3: Copy shared files — 2026-09-01T06:42:33.461Z

Copied project-root `INSTRUCTION.md` to `tasks/task_2219_merchant_underwriting_portfolio_risk_monitoring/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T07:01:10.303Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2219_merchant_underwriting_portfolio_risk_monitoring/workspace/PRD.md` — 492 lines, ~13,500 words, 102 KB. Document ends at §5 as required.

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or parsed (every script loads `SCAFFOLD.yaml` only). No sibling task directory was read.

## Structure

- **§1 Introduction** — 3 paragraphs: the four connected domains (underwriting, portfolio monitoring, money movement, enforcement/remedy) and the two design commitments (reproducible arithmetic, no unilateral irreversible action).
- **§2 Global Specs** — 12 subsections: 2.1 RBAC, 2.2 response envelope (verbatim), 2.3 pagination + filters, 2.4 identity/audit/logical clock, 2.5 money-bps-rounding discipline, 2.6 the 53-rank rejection ladder, 2.7 two independent merchant state dimensions, 2.8 named cascades + hierarchical consistency, 2.9 OCC, 2.10 reverse-reachability reads + left-to-right path validation, 2.11 segregation of duties, 2.12 reserve ledger invariants.
- **§3 Business Logic** — 13 subsections, intake through portfolio loss forecasting.
- **§4** — 63-row endpoint table (4 columns), preceded by the 201/200 status rule.
- **§5** — 53-row error table (2 columns).

## Coverage audit

| Dimension | Result |
|---|---|
| Entity field / body-input / response-field / path-param names | **182 / 182** verbatim in backticks |
| Entity type names | 15 / 15 |
| State literals | 38 / 38 |
| Role names | 6 / 6 |
| Endpoints | 63 / 63, exact scaffold order, all role sets match |
| Errors | 53 / 53 in §5 (exact scaffold order, zero HTTP-status mismatches) and all 53 also cited in §2/§3 prose |
| Validations | 53 / 53 — §2.6 reproduces every error ID in exact priority order 1→53 (programmatically confirmed identical) |
| Calculations | 7 / 7, all 36 constants present; 3 dual-variant calcs with both branches and their divergence documented |
| State transitions | 78 / 78 (40 written as `FROM → TO`, 38 in prose; each of the 38 individually audited) |
| Cascades | 6 / 6 named (CB-BREACH, ALERT-ESCALATION, REMEDIATION-PASS, REMEDIATION-FAIL, TERMINATION-EXEC, APPEAL-GRANT) with pinned fan-out ordering |
| OCC rules | 2 / 2 with their 412 error IDs |

**Hard contracts:** Contract 1 (field-name coverage) PASS — verified over three independent extraction passes; the first pass used wrong scaffold keys (`request_body_fields` instead of the actual `input`/`output`), which the corrected pass caught, plus a raw-text snake_case sweep whose only residuals are formula-local variables (`raw_hold_cents`, `pd_bps`, `deficit_cents`, …) and scaffold metadata keys, none of which are persisted or wire-visible. Contract 2 (rule coverage) PASS. Contract 3 (§3 path purity) PASS — zero path-like or method-like tokens in §3 backticks and zero bare HTTP method words in §2 or §3. §2.2 is byte-identical to the source file. No pseudocode operators and no fuzzy quantifiers.

## Scaffold contradictions resolved

Three internal conflicts were decided in favour of the more specific text; implementers and test authors should be aware:

1. **BeneficialOwner status derivation** — §1.1/§1.2 imply sanctions → PEP → ID; §1.5 states a "pinned order" twice. Followed the endpoint's pinned order: `SANCTIONS_HIT`, else `ID_UNVERIFIED`, else `FLAGGED_PEP`, else `CLEARED`.
2. **BusinessVerification precondition** — endpoint text says "SUBMITTED or INFO_REQUESTED"; §1.2 declares only `SUBMITTED → IN_VERIFICATION` and validation rank 17 defers to §1.2. Required `SUBMITTED`.
3. **`lifetime_reversed_cents`** — entity says "sum of `net_payout_cents` over REVERSED batches"; the reverse endpoint says accumulate `uncovered_loss_cents` + `reserve_offset_cents` + `loss_offset_from_settlement_cents`. Wrote the endpoint side-effect as normative.

Also noted: the scaffold's `difficulty_level` comment says 61 endpoints, but the parsed `endpoints[]` list and `worklog.md` both say 63. Used 63.

## Step 5: Generate unit tests — 2026-09-01T08:20:10.658Z

Suite complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2219_merchant_underwriting_portfolio_risk_monitoring/`:

## Files

**`test_helpers/`** (Stage 1, unchanged this session): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**`test_suite/`** — `conftest.py` + 17 test modules, **125 tests total**, all collected by pytest with no import errors:

| file | tests | source |
|---|---|---|
| test_01_reserve_requirement_pricing.py | 5 | Queue A |
| test_02_settlement_rounding_and_conservation.py | 6 | Queue A |
| test_03_portfolio_forecast_variants.py | 5 | Queue A |
| test_04_merchant_dimensions_and_appeal_loop.py | 4 | Queue A |
| test_05_risk_cascades.py | 5 | Queue A |
| test_06_rejection_ladder_conflicts.py | 6 | Queue A |
| test_07_threshold_boundaries.py | 4 | Queue A |
| test_08_cross_entity_gates.py | 4 | Queue A |
| test_09_window_geometry.py | 4 | Queue A |
| test_10_application_entities.py | 13 | Corner/entities |
| test_11_state_machines.py | 16 | Corner/state_machines |
| test_12_calculations.py | 11 | Corner/calculations |
| test_13_validation_precedence.py | 11 | Corner/validations |
| test_14_endpoint_reads.py | 14 | Corner/endpoints |
| test_15_error_conditions.py | 9 | Corner/errors |
| test_16_rbac.py | 5 | Corner/rbac |
| test_17_cross_cutting_and_consistency.py | 3 | Corner/cross-cutting + consistency |

## Coverage

- **Queue A (difficulty):** 20/20 instances, 43 tests, every instance ≥ 2 tests.
- **Queue B (corner):** 82 tests covering 81 of the 82 non-stub instances (entities 13/13, state_machines 16/16, calculations 11/11, validations 11/12, endpoints 14/14, errors 9/9, rbac 5/5, cross-cutting 2/2, consistency 1/1). The 22 `excluded_because:` stubs were not translated.
- Verification passes all green: exactly one trailing `Design:` line per test resolving to a real non-stub instance (no bad/dual/stub tags); every PRD citation contains an ≥8-word run that greps literally in PRD.md, with no unmatched tokens other than the accepted `—`→` - ` and `→`→`->` normalizations; `pyflakes` clean on `test_suite/`; every imported helper name resolves.

## Skipped instance

- `Corner/validations/ownership_coverage_outranks_the_verification_check` — unbuildable under the PRD. Advance-to-underwriting is only declared from `IN_VERIFICATION`, and an application in `IN_VERIFICATION` necessarily has a `PASSED` authoritative verification (a `FAILED` attempt drives it to `INFO_REQUESTED`, and recording is only declared from `SUBMITTED`); owners may only be attached in `DRAFT`. The two checks cannot co-occur, so the asserted `ERR_VERIFICATION_NOT_PASSED` is not uniquely derived. Left as a gap, per the contract.

## Design-vs-PRD deviations (PRD-derived value asserted instead)

1. `appeal_grant_cascades_...` (test_05): design says held 50 000; §3.12 `REINSTATEMENT_RELEASE` gives held 0 / released 50 000.
2. `hold_maturity_cutoff_inclusive_on_the_exact_day` (test_07): design says `RELEASING`; §3.10 requires held > 0 **and** released > 0, so the account stays `ACCRUING`.
3. Timestamp equality: §2.4 mandates three fractional digits, so tests use `.startswith("…T00:00:00")` rather than exact string equality.
4. `a_draft_remediation_program_...` (test_14): design says `network_program_tier` null; §3.11 says `STANDARD`.
5. `rejecting_a_termination_leaves_the_merchant_untouched` (test_14): design says `approved_by_user_id` null; §3.12 says rejection records it as the deciding user.
6. `an_appeal_is_reachable_…` (test_14) and `settlement_writes_are_already_visible_…` (test_17): design asserts `response_type` "Appeal"/"SettlementBatch"; §2.2 allows only `object`/`array`/`error`, so those assertions were dropped.
7. `a_successful_assessment_stales_the_token_that_created_it` (test_17): design says the `CHARGEBACK_WEIGHTED` retry yields 960 bps `ROLLING`, cap 2 000 000. §3.4 sums base 900 (band C) + chargeback uplift 960 = **1 860 bps `CAPPED`**, exposure 3 840 000, cap 7 680 000 — asserted instead.
8. `a_repeated_breach_bumps_recurrence_without_re_firing_the_cascade` (test_17): the design's second day row (1 000 000 cents) would also trip `VELOCITY_SPIKE` (baseline 33 333 × 3), contradicting its own "alert count stays 1". The day's volume was set to 90 000 cents, keeping the trailing count ratio at 90 bps while leaving the instance's claim intact.

Scope constraint honoured: no sibling task directory and nothing under `workspace/implementation/` was read, listed or written.

## Step 6: Generate implementation — 2026-09-01T08:20:10.658Z

Implementation complete and verified.

## Files created (all under `.../workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 15 | Guarded `pip install`, then `exec python3 app.py` on `$PORT` (default 10000), foreground |
| `app.py` | 59 | `create_app()`, 4 blueprints, error handlers (`ApiError`, 400/404/405/500) |
| `db.py` | 77 | In-memory `Store`: 15 dicts + logical clock, nothing seeded |
| `util.py` | 95 | ids, ISO timestamps, date math, half-up `rhu_div`, `ceil_div` |
| `errors.py` | 91 | 53-entry error catalog → HTTP status, `fail()` |
| `response.py` | 51 | envelope builders (object / array / paged / error) |
| `middleware.py` | 387 | auth + role gate, ownership checks, body/query validators, pagination, filters, per-request single version bump, entity finders |
| `services/calc.py` | 320 | reserve pricing, settlement waterfall, release lag, 4 detectors, gating bands, remediation month evaluation, portfolio forecast |
| `services/metrics.py` | 203 | trailing windows, ratios, counter recomputation, releasable balance, active book |
| `services/ledger.py` | 61 | append-only reserve ledger + account state machine |
| `services/cascades.py` | 219 | the 6 named cascades + shared funding hold/release links |
| `routes/applications.py` | 582 | 20 endpoints (category rules, applications, owners, verifications, assessments, decision) |
| `routes/portfolio.py` | 345 | 12 endpoints (day activity, risk summary, monitoring runs, alerts, funding holds/release) |
| `routes/settlement.py` | 380 | 11 endpoints (settlement batches, pay/reverse, reserve accounts, ledger, release requests) |
| `routes/enforcement.py` | 535 | 20 endpoints (remediation, termination, appeals, forecasts, clock) |
| `requirements.txt` | 1 | `flask>=3.0.0` |

Total 3421 lines. No `__init__.py` needed (namespace packages); `__pycache__` removed and suppressed via `PYTHONDONTWRITEBYTECODE`.

## Endpoint coverage
63 / 63. `app.url_map` yields exactly 63 method+path pairs, matching the scaffold's endpoint list one-for-one.

## Boot / isolation confirmation
- `bash start.sh` boots and serves; on a fresh boot `GET /merchants` and `GET /merchant-applications` both return `{"data":[], "total_count":0}` — nothing seeded, so per-test-server isolation gives every test a clean store.
- Storage is Python dicts only. A grep for `sqlite`, `open(`, `json.dump`, `pickle`, `shelve` across the tree returns nothing.

## Behavioural verification (two end-to-end smoke suites, ~90 assertions, both green)
- Suite 1: full happy path — category rule → application → owner → verification (fail → `INFO_REQUESTED` → resubmit → pass) → screening → underwriting → assessment (incl. `ERR_STALE_APPLICATION_VERSION` 412) → approve → merchant + reserve account by cascade → activity → monitoring → settlement batch (per-batch invariant `gross = net + hold + loss_offset` asserted) → pay → reserve release after maturity (+412 on stale retry) → forecast → termination (SoD 403, approve, execute) → appeal (review / request-info / respond / SoD 403 / GRANT reinstatement) → remediation pass. Conservation invariant `total_accrued = held + released + offset` asserted at each checkpoint.
- Suite 2: the cascades suite 1 didn't reach — CB-BREACH (`RESTRICTED`/`DELAYED`/7 days/`remediation_required`), idempotent re-detection (`recurrence_count` 2, severity overwritten), DELAYED payout dating (`period_end + 7`), manual funding hold/release with batch fan-out, batch reversal (`lifetime_reversed = uncovered + reserve_offset + loss_offset`), CARD_TESTING detector → ALERT-ESCALATION (`funding_state HELD`, reason `CARD_TESTING`, `account_state` untouched), REMEDIATION-FAIL → `NETWORK_ESCALATED` + tier `EXCESSIVE` + `EXCESSIVE_CHARGEBACKS` hold, termination blocked while a program is open then permitted once terminal, activity rejected on a TERMINATED merchant, superseding-application reverse read, withdraw, DECLINE (400 without `decline_reason_code`), and the rejection-ladder/pagination/ownership negatives (400 bad limit, 400 bad enum, 403 wrong owner, 403 wrong role, 404 unknown id).

Spot-checked arithmetic against PRD prose: band D thin-file CHARGEBACK_WEIGHTED case yields `base 1500 + thin 300 + cb 900 = 2700 → clamp 2500`, `exposure = max(12000, 3333) = 12000`, `cap = min(25000×6, 2×12000) = 24000`, type `CAPPED`; band A case floors at 100 bps → `ROLLING` → 90-day release lag. All four detector thresholds, the 30-day fixed-denominator baseline, and the remediation fail/pass ordering were re-read against the PRD and match.

Also removed two leftover `_unused()` placeholder functions and their dead imports from `routes/applications.py` and `routes/portfolio.py`.

## Step 7: Run tests and iterate — 2026-09-01T08:50:00.000Z

Clean 8-round parallel sweep: **125/125 passing in all 8 rounds.**

## Summary

**Iterations run:** 2 (baseline sweep 120/125 in all 8 rounds with an identical, non-flaky failure set of 5; second sweep 125/125 in all 8 rounds).

**Tests deleted:** none. One assertion pair was removed under STEP 1c partial-coverage handling (below); no whole test was deleted, since every failure traced to either a test-fixture violation of a PRD schema rule, a test mis-translation of the PRD rejection ladder, or a real implementation ladder-ordering bug.

**Fixes applied to `test_suite/`**

- `test_suite/test_06_rejection_ladder_conflicts.py` — `TestTheSanctionsStopBeatsThinOwnership._advance_a_sanctioned_thin_application` built its beneficial owner with `country_code="RU"`. PRD §3.1 states the owner payload carries "a `country_code` of `US` or `CA`", so the PRD-faithful implementation correctly returned `ERR_INVALID_REQUEST` at setup and both tests in the class errored. Changed to `"US"`; the sanctions-vs-coverage precedence the class exists to prove is untouched (owner still holds only 60.00 percent and still screens `SANCTIONS_HIT`).

- `test_suite/test_11_state_machines.py` — `test_a_second_execution_of_the_same_termination_is_rejected` asserted `ERR_TERMINATION_STATE_INVALID`. The first execution leaves the merchant `TERMINATED`, and PRD §2.6 step 7 fixes the state-guard sub-order as merchant `account_state` **before** termination-decision state ("This ordering is normative"), while §3.12 makes the merchant guard an explicit precondition of execute ("Execution requires the merchant's `account_state` to be `ACTIVE` or `RESTRICTED`"). Corrected the expected `error_id` to `ERR_MERCHANT_ACCOUNT_STATE_INVALID` (still an exact error_id assertion, not an HTTP-status downgrade) and cited the ladder in the docstring.

- `test_suite/test_10_application_entities.py` — `test_identifiers_timestamps_and_versions_are_owned_by_the_server` asserted `created_at`/`updated_at` are drawn from the logical clock (`startswith("2026-08-01T00:00:00")` / `startswith("2026-08-03T09:30:00")`). **DEFAULT/SOURCE SILENCE**: PRD §2.4 defines the two audit fields but never names their clock, and every stamp the PRD *does* route through the logical clock is named individually (`decided_at`, `screened_at`, `paid_at`, `executed_at`, `terminated_at`, `reinstated_at`, `filed_on_date`, …); moreover §2.8/§3.x repeatedly use `created_at` as a strict tiebreaker ("breaking ties by `created_at` ascending"), which a rewindable logical clock could not provide. Two PRD-faithful readings therefore exist, so the two clock-value assertions were removed and replaced with the verbatim-covered behaviour: `created_at` unchanged across a mutation, `updated_at` refreshed on the mutation, `version` starting at 1 and incrementing, `id` stable. (Scaffold rule that drove the assertions: `Corner/entities/system_fields_id_timestamps_and_version_are_server_owned`.)

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`**

- `routes/applications.py`, `routes/portfolio.py`, `routes/settlement.py`, `routes/enforcement.py` — every reverse-reachability list handler (`list_owners`, `list_verifications`, `list_assessments`, `list_superseding`, `list_onboarded`, `list_activity`, `list_alerts`, `list_merchant_reserve_accounts`, `list_batches`, `batch_ledger_entries`, `account_ledger_entries`, `list_programs`, `list_terminations`, `list_merchant_appeals`, `list_decision_appeals`) ran `find_*()` / `own_*()` before `pagination()` and the `filter_*()` query validators, inverting PRD §2.6's normative ladder (step 3 Schema — including "`limit` within 1 through 100" — precedes step 4 Existence and step 5 Ownership). Moved the query-schema validators ahead of the existence and ownership lookups in each handler. This was the real bug behind `test_the_schema_check_outranks_the_existence_lookup`, which was faithful to PRD as written.

**Orchestrator verification note:** the subagent's `results.{1..8}.json` were absent from disk at hand-off, so the orchestrator re-ran the full 8-round parallel sweep independently. Result confirmed: 125 passed / 125 total / 0 failed in each of rounds 1–8. Fresh `results.{1..8}.json` written to `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-09-01T08:55:11.193Z

`PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 491 lines — `PRD_FINALIZED.md`: 491 lines — **0.00% line delta** (2 existing lines revised in place, no lines added or removed, no new sections).

## Changes

- **§2.4 (Resource Identity, Audit Fields and the Logical Clock)** — *insert* — appended to the audit-fields paragraph that `created_at`/`updated_at` are stamped from **real wall-clock UTC**, not the logical clock (so moving the clock never changes them), and that every `created_at` ascending ordering / tie-breaker in the document resolves to the server's row-creation sequence — `implementation/db.py:56-64` (`new_row()` → `now_ts()`), `implementation/util.py:34-35`, `implementation/middleware.py:56-70` (`touch()`), `implementation/db.py:67-69` (`by_seq`).
- **§2.4 (same section, logical-clock paragraph)** — *revise* — prefixed "All date and datetime rules … read a **logical clock**" with "Apart from the two audit stamps just described," so the universal claim no longer contradicts the inserted sentence — `implementation/db.py:46-50` vs `implementation/db.py:58`.

## Step 7 items that needed **no** PRD edit
- **test_06 `country_code="RU"`** — pure test-fixture bug. PRD §3.1 already pins the owner payload's `country_code` to `US` or `CA`, and `routes/applications.py:271` enforces exactly that enum. No silence.
- **test_11 re-execution error id** — PRD already determines it. §2.6 step 7's sub-order (merchant `account_state` before termination-decision state) plus §3.12's explicit precondition match `routes/enforcement.py:273-281` exactly (merchant → `ERR_PROGRAM_STATE_INVALID` → `ERR_TERMINATION_STATE_INVALID`). The test was mistranslating the ladder.
- **Reverse-reachability list ladder fix (impl fix)** — this moved impl *toward* PRD, not away. §2.6 steps 3→4→5 already normatively pin Schema (incl. `limit` 1–100) before Existence before Ownership; after the fix all 15 handlers do `filter_*()` → `pagination()` → `find_*()` → `own_*()`. Verbatim prose kept.

## Per-edit pre-edit search log

**Edit 1 + 2 (single subject, two sentences)**
- **(a) Subject:** the clock source of the `created_at`/`updated_at` audit stamps, and the consequent resolution of every "`created_at` ascending" ordering.
- **(b) Impl paths enumerated (read/grepped):**
  - Stamping: `db.py:56-64` (`new_row`, both stamps = `util.now_ts()`), `util.py:34-35` (`datetime.now(timezone.utc)`), `middleware.py:56-70` (`touch`, `updated_at = now_ts()`), `db.py:14-15` (no-version types carry only `created_at`, also wall clock).
  - Logical clock (must remain unaffected): `db.py:11-12,46-50`; every logical-clock stamp — `applications.py:254` (`decided_at` on withdraw), `:335` (`screened_at`), `:512` (`decided_at` on decision); `settlement.py:203` (`paid_at`), `:227` (`reversed_at`), `:158/:288/:348` (`effective_date`, releasable cutoff); `enforcement.py:283-285` (`executed_at`), `:331-335,349` (`filed_on_date`, appeal window), `:425-426` (`decided_at`); `services/cascades.py` (`terminated_at`, `reinstated_at`); `portfolio.py:160,217` (activity-date / regression checks).
  - Ordering/tiebreak paths (all `_seq`, i.e. insertion order): `db.py:67-69`; `applications.py:105,118,198,211`; `portfolio.py:78,200`; `settlement.py:91,183,272,298,314`; `enforcement.py:188,471,519`; `services/metrics.py:30-32,36,40,47,51,55,59,63,77,84,93,196` (incl. the §3.10 prior-scheduled-release "greater `created_at`" tiebreak at `:196`).
  - Envelope timestamp: `response.py:4-10` (`api_request_timestamp` also uses `now_ts()`).
- **(c) Wording adjustments made:**
  1. Dropped a drafted clause calling the audit stamps "the one exception to the logical clock" — `response.py:10`'s `api_request_timestamp` is also wall-clock while PRD §2.2 leaves its source unstated, so an exhaustive "only exception" claim would have been a false universal. Replaced with the non-exhaustive "stand apart from the logical clock described below".
  2. Dropped a drafted clause "and they are never used as a date input to any rule" — `created_at` *is* load-bearing as an ordering key and as the §2.8/§3.10 tiebreaker (`metrics.py:196`), so the clause would have mis-described those paths.
  3. Widened the tiebreak sentence from "the tie-breakers of §2.8" to "the tie-breakers of §2.8 and §3", because `_seq` also resolves the §3.7/§3.8/§3.11/§3.12 cascade orderings and the §3.10 prior-release selection, not only the §2.8 statement.
  4. Scoped the §2.4 universal ("All date and datetime rules … read a logical clock") rather than leaving it to contradict the insert — the softening is a narrowing of a PRD claim the impl does not satisfy, not a new claim.

## Step 9: Complete PRD — 2026-09-01T09:15:43.477Z

Reconciliation complete.

## Files

| | lines | chars |
|---|---|---|
| `PRD_FINALIZED.md` (source) | 491 | 102,965 |
| `PRD_COMPLETED.md` | 491 | 109,215 |

Char delta: **+6,250** on 31 changed lines (verified: every changed line grew — all edits are in-paragraph inserts/revisions; no new sections, no new paragraphs, line count unchanged).

## Counts
- **ambiguity-pins: 24**
- **mismatch-revisions: 8**
- 32 pins total across 31 lines (two pins share the GRANT paragraph).

## Changes

- §2.1 Roles — insert — ambiguity — for a resource that names no merchant in path or body (batch, reserve account, remediation program, termination decision, appeal, appeal listing), `MerchantUser` ownership compares the addressed row's stored `merchant_id` — `middleware.py:385`, `routes/settlement.py:172`
- §2.2 `data` bullet — insert — ambiguity — the logical-clock op is the only one returning an empty `data` object — `routes/enforcement.py:535`
- §2.2 pagination bullet — insert — ambiguity — pagination meta appears on list endpoints only; the §3.7 sweep is an `array` envelope with none of the four; `has_more` = `offset + rows_returned < total_count` — `response.py:41`, `routes/portfolio.py:240`
- §2.3 Collections — insert — ambiguity — empty-string filter treated as absent; unknown enum member → `ERR_INVALID_REQUEST`; `from_date`/`to_date` must be `YYYY-MM-DD`; `remediation_required` accepts `true|false|1|0`; `mcc_code` matched as a literal with no format check — `middleware.py:256-301`
- §2.4 Audit fields — revise — mismatch — `version` advances by exactly one per request however many times the request writes the row; `updated_at` refreshes on each write; `created_at` ties resolved by server row-creation sequence — `middleware.py:56-70`
- §2.4 Logical clock — insert — ambiguity — clock-set requires a well-formed ISO `now_utc` (missing/malformed → `ERR_INVALID_REQUEST`) and answers `200` with empty `data` — `routes/enforcement.py:528-535`
- §2.8 Cascades — revise — mismatch — the version increment lands once for the whole request, not once per link — `middleware.py:56-70`
- §2.12 Reserve ledger — revise — mismatch — `recorded_by_user_id` is always populated (no automated appender); the reinstatement release carries the appeal-deciding approver — `services/cascades.py:206-212`
- §3.1 Category rules — insert — ambiguity — `category` is a required non-blank string ≤200 chars, free-form, never enum-checked — `routes/applications.py:87`
- §3.1 Beneficial owners — insert — ambiguity — `ownership_pct` stored verbatim (finer precision accepted); the 2-decimal rounding applies per-owner when forming `owner_ownership_pct_total` — `routes/applications.py:59-63,268`
- §3.2 Info requests — insert + revise — ambiguity + mismatch — manual `outstanding_info_items` is a required list of strings, possibly empty, stored verbatim, never enum-checked; and the operation resolves application existence *ahead of* body schema (unknown app → `ERR_APPLICATION_NOT_FOUND` even with the field missing) — `routes/applications.py:233-243`
- §3.3 Underwriting gate — revise — mismatch — category and ownership-coverage checks read the application's own stored `mcc_disposition` / `owner_ownership_pct_total`, not recomputed sibling data — `routes/applications.py:407-423`
- §3.5 Committee decision — insert — ambiguity — both outcomes answer with the updated application, not the merchant or reserve account an approval creates — `routes/applications.py:518,572`
- §3.7 Monitoring sweep — insert — ambiguity — a forward-dated `as_of_date` is also `ERR_MONITORING_RUN_DATE_REGRESSION`; response is a `201` array envelope with no pagination fields — `routes/portfolio.py:217-219,240`
- §3.7 CB-BREACH — insert — ambiguity — link four hangs off link three, so a merchant already `DELAYED`/`HELD` gets no batch re-dated — `services/cascades.py:70-78`
- §3.8 Alert review — revise — mismatch — all three dispositions record `reviewed_by_user_id`, overwrite `review_note` (null when omitted) and recompute `open_alert_count` — `routes/portfolio.py:292,302-313`
- §3.8 Funding release — insert — ambiguity — `TERMINATED` is rejected first with `ERR_MERCHANT_ACCOUNT_STATE_INVALID`, before the `HELD` check — `routes/portfolio.py:340-343`
- §3.9 Reserve state on hold — insert — ambiguity — `RELEASING → ACCRUING → CAP_REACHED` chains within a single `HOLD` append — `services/ledger.py:38-44`
- §3.9 Paying out — revise — mismatch — no separate `funding_state` guard on pay; the batch-state guard covers held funding — `routes/settlement.py:190-200`
- §3.9 Reversing — insert — ambiguity — the compensating `HOLD` uses `effective_date` = logical clock date (not period end) and `settlement_batch_id` = this batch — `routes/settlement.py:242-251`
- §3.10 Releasable balance — insert — ambiguity — `releasable_balance_cents` is computed at read time and present only on the single-account fetch — `routes/settlement.py:287-289`
- §3.10 Release request — insert — ambiguity — `amount_cents` must be at least 1 — `routes/settlement.py:327`
- §3.10 Release response — insert — ambiguity — the `201` body is the appended `ReserveLedgerEntry`, not the account — `routes/settlement.py:366-380`
- §3.10 Release state moves — revise — mismatch — `CAP_REACHED → RELEASING` only on a `RELEASE` entry; `OFFSET_LOSS` never opens `RELEASING` — `services/ledger.py:46-56`
- §3.11 Remediation windows — insert — ambiguity — no upper bound on `month_index`; monthly blocks are not clipped to `window_end_date` — `services/calc.py:243-247`
- §3.11 REMEDIATION-PASS — insert — ambiguity — links are strictly nested; a merchant not `RESTRICTED`, with a pending termination, or whose funding is not `DELAYED` skips the downstream links — `services/cascades.py:98-123`
- §3.12 Termination rejection — insert — ambiguity — `rejection_note` is required, non-blank, ≤2000 chars — `routes/enforcement.py:251`
- §3.12 Appeal filing — insert — ambiguity — appeal info items are a required list; `response_text` is required ≤4000 chars and is not persisted — `routes/enforcement.py:377,392`
- §3.12 Appeal decision — insert — ambiguity — `reinstatement_reserve_pct_bps` accepts 0–10000 — `routes/enforcement.py:410`
- §3.12 GRANT — insert — ambiguity — `GRANT` against a non-`EXECUTED` decision raises `ERR_TERMINATION_STATE_INVALID` before the appeal state guard and before segregation of duties — `routes/enforcement.py:414-423`
- §3.12 APPEAL-GRANT — insert — ambiguity — batch re-dating and reserve-account reopening are nested inside the `funding_state == HELD` branch — `services/cascades.py:184-195`
- §3.13 Forecasts — insert — ambiguity — `stress_multiplier_bps` is persisted even under `EXPECTED_LOSS`; `as_of_date` is unconstrained relative to the clock — `routes/enforcement.py:485-502`

Verified as already uniquely pinned (no edit): all §4 RBAC role lists vs every `authenticate([...])`; every declared sort order and tie-breaker; the complete §5 error/HTTP-status catalogue; all seven formulas and constants in `services/calc.py`; and the rejection-ladder position of every guard other than request-info. Deliberately not pinned as outside the documented API surface: the Flask fallback `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` handlers and `strict_slashes=False` trailing-slash tolerance.

**Orchestrator verification:** `PRD_COMPLETED.md` present at 491 lines / 109,215 chars; diff vs `PRD_FINALIZED.md` is 62 changed lines (31 revised pairs), no additions or deletions. Pipeline complete.
