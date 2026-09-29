# Worklog — task_2638_insurance_premium_finance

## Step 1: Create task directory — 2026-09-03T23:17:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2638_insurance_premium_finance` and `workspace/` (pre-assigned path; no index auto-allocation).

## Step 2: Generate scaffold — 2026-09-04T01:48:00.000Z

All three scaffold artifacts for task 2638 are complete and lint clean.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2638_insurance_premium_finance/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2638_insurance_premium_finance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2638_insurance_premium_finance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  1323

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files and line counts

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2940 | 152675 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2330 | 173248 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5533 | 418867 |

`SCAFFOLD.yaml` top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. The other two files each hold exactly one top-level key.

## Contents
- SCAFFOLD: 15 entities, 12 state machines (parallel shape), 2 §1.2.1 OCC rules, 7 calculations, 42 ordered validations, 46 endpoints, 53 error codes, 5 roles (segregation_of_duties, three entity-backed).
- §1.8: 9 `rule_id` blocks x 2 instances = 18, unchanged from the earlier pass.
- §1.9: all nine claim-extraction-guide sections walked — entities 12, state_machines 9 live + 5 stubs, calculations 7 + 6, validations 5 + 4, endpoints 5 + 1, errors 4, rbac 3, cross_cutting_complexity_layers 2 + 2, consistency_model 1. 66 instances total, 48 with full recipes; every `excluded_because` stub cites an existing §1.8 instance name.

## Work completed this session (rbac → end)
- rbac: role matrix with the two orderings implementations invert (401 before 403, 403 before 404 on a ghost id), entity-backed row ownership across two insureds / two agencies / two carriers (`ERR_NOT_RESOURCE_OWNER` vs `ERR_VERIFIER_NOT_AUTHORIZED`), and the two same-user rules staged so only the identity collides while roles stay correct.
- Layers: OCC live on `POST /agreements/{id}/endorsement-financings` (stale → 412, refused request leaves the version un-advanced, replay of a previously-valid version refused, missing OCC field → 422); `dual_variant_calculation` promoted from stub to live after finding the SHORT_RATE unearned-premium variant had no coverage anywhere; cascading_side_effects and rate_threshold_triggers stubbed against §1.8.
- consistency_model: `immediate` asserted in the strong form (derived values correct in the causing write's response, immediate read agrees).
- Added a missing `initial_state` instance (guide Table 2 row) covering 10 of 12 machines, including the two born only as side effects.

## Two defects found and fixed in SCAFFOLD.yaml
1. `ERR_NOTICE_WINDOW_OPEN` (priority 34) was unreachable: priority 12 required stage `LATE` for issuance, so a duplicate notice always reported `ERR_DELINQUENCY_STATE_INVALID` and no state path admits an ISSUED notice with stage `LATE`. Priority 12's issuance clause now admits `LATE` or `NOIC_ISSUED` and defers to priority 34 for the precise reason; the code is now triggered and asserted in the deficiency error walk.
2. Arithmetic correction while writing the SOD recipe: the Rule-of-78s rebate is clamped by `unpaid_finance_charge_cents`, so a 1000-cent payment made before cancellation drops the rebate from 37650 to 36650 — asserted explicitly as a trap.

All 53 error codes now appear in at least one `assert` line across the two design files; no duplicate instance names; no forbidden concurrency vocabulary.

## Step 3: Copy shared files — 2026-09-04T01:49:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T02:10:00.000Z

PRD complete.

**Output:** `workspace/PRD.md`
**Final line count:** 438 lines (14,262 words, 102,799 bytes)
**Last section heading:** `## 5. Error Code Catalogue` — file ends on the last table row (`| ERR_OFFSET_EXCEEDS_RESERVE | 422 |`), a real section boundary; no audit footer inside the file.

**Structure:** §1 Introduction; §2 with 11 subsections (2.1 Role-Based Access Control, 2.2 API Response Structure emitted byte-verbatim from `section-2.2-response-structure.md`, 2.3 Pagination, 2.4 Common Resource Properties and Row Versions, 2.5 The Logical Clock, 2.6 Cents/Basis Points/Rounding, 2.7 Path Resolution and Referential Reachability, 2.8 Optimistic Concurrency, 2.9 Statutory Rate Regimes and Licensing, 2.10 Order of Rejection — all 42 priorities, 2.11 Two Conservation Identities); §3 with 9 workflow subsections; §4 46-endpoint table (4 columns); §5 53-error table (2 columns).

**Contract 1 — Field-Name Coverage: PASS.** Programmatic diff of scaffold identifiers against backticked tokens in PRD.md: 129 entity/path/query identifiers required → 0 missing; every endpoint `input` field name → 0 missing. All 15 entities named, all 5 roles named, all 38 state-machine state literals present.

**Contract 2 — Rule Coverage: PASS.** All 42 validations' `error_id`s appear in the §2.10 precedence list (the two 404s in priorities 3–4 are carried by the explicit left-to-right / declared-order not-found rules in §2.7, cross-referenced from §2.10 items 3 and 4). All 7 calculations with formulas reconstructible from prose, all constants present as concrete values (tier ceilings as 5,000 / 20,000 dollars; deficiency-fee tier as 250 dollars; rates as 1800/1500/1200 bps; fees as 25/50 dollars), and both branches of every variant pair covered with their asymmetric consequences (PROVISIONAL/FINAL, STANDARD/PAYOFF, PRO_RATA/SHORT_RATE, RULE_OF_78/ACTUARIAL, COMMISSION_CAPPED/RESERVE_CAPPED, ADD_ON/SIMPLE_INTEREST). All 12 state machines / 50 transitions covered including the non-obvious ones: `PENDING_VERIFICATION`→`DRAFT` regression, `PAID_IN_FULL`→`ACTIVE`, the `PAID`→`PAST_DUE` vs `PAID`→`SCHEDULED` date-dependent reversal fork, `SCHEDULED`→`VOIDED` from both restructure and cancellation execution, `ISSUED`→`CURED` from both payment and waiver, `RETURN_POSTED` vs `CLOSED_NO_RETURN`, `PARTIALLY_OFFSET` self-loop, `SUSPENDED_FOR_CHARGEBACKS`→`ACTIVE`. Both OCC rules (`expected_agreement_version`, `expected_chargeback_version`) and both SoD rules covered. Endpoint role sets in §4 match the scaffold exactly (46/46, zero role mismatches); error IDs and HTTP statuses match exactly (53/53, zero status mismatches).

**Contract 3 — §3 Path Purity: PASS.** Scan of §3 found 0 backticked tokens starting with `/`, 0 bare HTTP method tokens, 0 method+path pairs, and 0 raw slash-paths outside backticks. No pseudocode blocks (the only 2 code fences are the two JSON envelopes inside §2.2) and no fuzzy-language hits.

**Ambiguities resolved (scaffold self-contradictions), each decided for self-consistency and stated deterministically in the PRD:**
1. Restructure successor is minted `ACTIVE` with a fresh schedule (endpoint text) rather than `DRAFT` (status-table text) — a `DRAFT` successor could never be submitted, since submit requires all policies `PENDING_VERIFICATION` while carried-over policies are `VERIFIED`.
2. Predecessor `delinquency_stage` after restructure → `CURRENT` (status-table side effect) rather than `CANCELLED` (endpoint text).
3. Successor `down_payment_cents` and `service_fee_cents` are 0, with `additional_down_payment_cents` netted out of `carried_over_balance_cents`, avoiding a double subtraction in the amount-financed formula.
4. `active_agreement_count` decrements only on void out of `PENDING_VERIFICATION`, not out of `DRAFT` (per the state machine).
5. Two preconditions the scaffold left without codes were mapped: notice issuance needing an `OUTSTANDING` late fee → `ERR_DELINQUENCY_STATE_INVALID` (409); cancellation execution needing a `VERIFIED` policy → `ERR_POLICY_NOT_VERIFIED` (422).
6. `gross_balance_cents` defined as `principal_balance_cents` plus post-rebate `unpaid_finance_charge_cents`.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator truncation check:** `tail -12` confirms the file ends mid-table-boundary at the final declared error row; heading scan shows all 5 top-level sections and all 20 subsections present. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T04:05:00.000Z

All queue A and queue B work is complete. Final state of the generation:

## Output

`test_helpers/` (2,912 lines)
- `__init__.py` 181, `api_client.py` 356, `api_errors.py` 136, `assertions.py` 584, `constants.py` 124, `factories.py` 313, `fixtures.py` 663, `test_users.py` 94, `types.py` 461

`test_suite/` (14,450 lines, **425 tests**)
- `conftest.py` 17 | `test_01_origination_pricing.py` 366 (7) | `test_02_licensing_gate.py` 323 (7) | `test_03_policy_terms_and_verification.py` 543 (10) | `test_04_premium_basis_divergence.py` 181 (3) | `test_05_servicing_and_late_fees.py` 210 (5) | `test_06_payment_waterfall_and_priority.py` 488 (11) | `test_07_delinquency_and_notice.py` 554 (16) | `test_08_cancellation_settlement.py` 844 (23) | `test_09_endorsement_financing.py` 309 (9) | `test_10_corner_entities.py` 1425 (53) | `test_11_corner_state_machines.py` 1518 (52) | `test_12_corner_calculations.py` 1154 (41) | `test_13_corner_validations.py` 1381 (42) | `test_14_corner_endpoints.py` 1408 (45) | `test_15_corner_errors.py` 1543 (46) | `test_16_corner_rbac.py` 1119 (29) | `test_17_corner_cross_cutting.py` 1067 (26)

Nothing was written under `workspace/`. Every file compiles, pyflakes is silent, and the citation/tag checker reports `PROBLEMS: 0` on all 17 files.

## Design-index coverage (complete)

Queue A 18/18 non-stub instances (all nine difficulty rules x2). Queue B 48/48: entities 12, state_machines 9, calculations 7, validations 5, endpoints 5, errors 4, rbac 3, cross_cutting 2, consistency_model 1. No stub instance is tagged, no tag points at a non-existent instance, every test carries exactly one `Design:` line as its docstring's last line.

## Findings worth relaying

Design-vs-PRD conflicts — in every case the test asserts the PRD-derived value:
- **`gross_balance_cents`** is principal + *post-rebate* unpaid finance charge (PRD lines 259/291). Three separate design instances get this wrong (`side_effect_conditional_cascade_execution_...` 419047 vs 414550; the rbac SoD instance 506497 vs 502000; the dual-variant instance 506497/1118935 vs 502000/1009000). I also **fixed three pre-existing assertions** written in earlier sessions: `test_08_cancellation_settlement.py` (two, were 506497) and `test_15_corner_errors.py` (one, was 539650).
- **Illegal setup in the dual-variant corner instance**: note K is funded with a 100000 down payment against a 1207000 premium basis under `min_down_payment_bps` 1500 (181050 required), so its submit could never succeed. The test uses 200000 and re-derives af 1009000 / fc 75675 / top 1084675 / installment 180779 / late fee 9039, leaving every unearned-premium figure the instance actually claims intact (pro-rata 516164 vs short-rate 464548, delta 51616; K302 233823, K305 236146; aggregate 934517 by per-policy rounding).
- **Illegal ordering in the rbac SoD instance**: it submits note A at clock 2026-10-12 with a 2026-10-01 first due date, which PRD lines 205/211 refuse. `test_16` splits the pricing legs onto a fixture that stays at 2026-08-15.
- `exclusive_operations_role_matrix_...` asserts `net_payoff_cents == 412059`; with one installment retired r = 5, so rebate 26893 and net 422816 (the consistency_model instance confirms both).
- `error_triggerable_statutory_ceiling_...` asserts version 2 after a rate-exception approval; policy attachment is a mutation (PRD 207), so it is 3.
- `standard_crud_agreement_...` asserts status `VOIDED`; the PRD status is `VOID`.
- Two instances assert `total_premium_cents` is null on a never-quoted note; PRD 203 zeroes it — tests assert `0` with `quote_basis is None`.
- `listing_agreements_paginated_and_filtered_by_insured` prose contradicts its own calls; followed the calls (A→3, B→1, all DRAFT→4).
- Dangling cross-reference: corner stub at `SCAFFOLD_CORNER_DESIGN.yaml:3900` names `difficulty_instance: cascading_side_effect_chain/payment_cure_cascade_...`, but that instance's real `rule_id` is `transitive_cascade`.

PRD-gap skips (sub-assertions omitted rather than weakened): the `ERR_PREMIUM_VARIANCE_EXCEEDED`/`PREMIUM_VARIANCE_TOLERANCE_BPS` claim about §3.8 return postings has no PRD support; `verified_policy_state_gates_endorsement_financing` expects the note's version to advance on mere endorsement creation (PRD §2.4 derives the opposite — test asserts unchanged); `computed_fields_on_financed_policy_...` assumes `corrected_effective_date` is optional and `financed_premium_cents == 0` at attachment (PRD 207/223 say otherwise — test asserts 600000).

Infrastructure bug fixed earlier in the run: `test_helpers/factories.py::rate_exception` used a non-existent field `approved_annual_rate_bps` and omitted the mandatory `justification`.

Note: `workspace/implementation/` now contains an implementation (app.py, routes_*.py, …) written concurrently by another agent. I deliberately did not run the suite against it — the tests are derived from the PRD only, and executing/tuning against that code is the pipeline's later sweep step, not part of generation.

## Step 6: Generate implementation — 2026-09-04T02:44:00.000Z

Implementation complete and smoke-tested.

## Files written to `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `core.py` | 459 | 53-error catalogue + `ApiError`, logical clock (epoch `2026-08-01T00:00:00Z`), in-memory `Store` (15 dicts), response envelope, RBAC, validators, pagination, `Fraction`-exact `round_half_up`, `add_months` |
| `model.py` | 366 | Path/FK lookups (each with its own 404 code), collection queries, live-computed derived fields, 15 per-entity serializers |
| `calc.py` | 456 | Pricing engine (ADD_ON vs SIMPLE_INTEREST), schedule generation, tail redistribution, rebate (RULE_OF_78 / ACTUARIAL), payoff, 4-bucket + PAYOFF allocation, exact reversal, late-fee band, unearned-premium (PRO_RATA / SHORT_RATE), deficiency + chargeback settlement |
| `gates.py` | 131 | Statutory/state gates and the cure / paid-in-full cascades |
| `routes_admin.py` | 240 | Rate regimes, licences, insureds, agents, insurers, `/_clock/set_current_utc` |
| `routes_agreements.py` | 523 | Agreements, policies, verifications, reopen, submit, activate, void, installments, rate exceptions, payoff quote |
| `routes_servicing.py` | 427 | Payments + reversal, late fees + waiver, servicing run, notices, power of attorney, carrier requests + return posting |
| `routes_endorsements.py` | 272 | Endorsements, decline, endorsement financing (OCC), restructure, chargebacks + offset (OCC) |
| `app.py` | 66 | Flask app, blueprints, `ApiError`/`HTTPException` handlers, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt`, `start.sh` | 1, 7 | Guarded pip install then `exec python3 app.py` |

All 46 endpoints registered; every file passes `python3 -m py_compile`. Storage is process-memory dicts only — no SQLite, no JSON on disk, no `/tmp` cache, and nothing is seeded at import or startup.

## Smoke test (free port 43737, killed by PID only)
Full happy path verified end to end: rule → licence → clock → insured/agent/insurer → draft → policy → submit (PROVISIONAL, tier 1500 bps) → two-party CONFIRMED → activate (schedule sums exactly to `total_of_payments_cents` and components to `finance_charge_cents`) → payoff quote → STANDARD payment (bucket-2 partial FC application) → reversal restoring `805000/100625` exactly → servicing run (`past_due_marked/late_fees_assessed/agreements_advanced_to_late`) → notice with frozen `past_due_amount_cents` → power of attorney (SOD enforced, rebate before installment voiding) → carrier return → `CANCELLED_DEFICIENT` with 5000-cent fee and `COMMISSION_CAPPED` chargeback → partial offset. Also verified: SIMPLE_INTEREST declining schedule, CORRECTED attestation moving the tier, endorsement financing with `ERR_STALE_AGREEMENT_VERSION`, restructure (carried-over balance 860000, predecessor `RESTRUCTURED` at zero balances, policies re-pointed with `carried_over: true`), dispute cascade un-pricing the note back to `DRAFT`, reopen superseding both attestations, ownership 403, pagination `has_more`, and 400/401/403/404/409/412/422 error shapes.

## Interpretation decisions worth flagging
- `version` bumps at most once per row per HTTP request (PRD 2.4 "exactly 1 on every mutation" vs. scaffold's multiple side effects).
- Derived counters (`active_agreement_count`, `policy_count`, `verified_policy_count`, `outstanding_chargeback_cents`, `is_effective`, `endorsed_premium_cents`) are computed at serialization time, which reproduces every prescribed increment/decrement without drift.
- `PremiumVerification` payloads carry only `id` + `created_at` + its own fields (no `updated_at`, no `version`) — confirmed in the smoke test.
- Errors with no catalogue entry (re-suspending a licence/agency, duplicate `naic_code`, duplicate `license_number` per regime, endorsement dated before `verified_effective_date`) map to `ERR_INVALID_REQUEST` (400).
- Rejection order follows PRD §2.10's numbered list, not the prose ordering, wherever the two disagree (notably rate-exception approval: service-fee cap 27 before rate ceiling 28; reopen-verification checks policy state 13 before agreement state, since reopen is absent from priority 11's `applies_to`).

## Step 7: Run tests and fix — 2026-09-04T04:58:00.000Z

Two 8-round parallel stability sweeps (`--isolation per-test-server`, 425 tests each round).

- **Sweep 1**: all 8 rounds bit-identical at `passed=408 failed=17 total=425` — zero flakiness, so none of the failures was host-load noise.
- **Sweep 2** (after the fixes below): all 8 rounds `passed=425 failed=0 errors=0 skipped=0`.

All 17 union failures were test-side defects. **Zero implementation changes.** No test deleted; one assertion narrowed under STEP 1c partial coverage.

Three recurring root causes:
1. Tests hardcoding note `version` totals that silently denied the policy-attachment bump PRD line 207 mandates ("increments the agreement's `policy_count` and advances the agreement's `version`") — 4 tests.
2. Test setups violating two §2.10 rejection priorities at once while asserting the lower-priority code — 4 tests (23 pre-empting 29; 7 pre-empting 11 twice; 11 pre-empting 31).
3. Fixture/arithmetic bugs in the tests' own preconditions — 9 tests.

Verified PRD-faithful and left untouched: `routes_servicing.post_payment` check order (body schema before agreement status), `routes_admin.set_clock` echo, `routes_endorsements` mandatory `expected_agreement_version` → `ERR_INVALID_REQUEST`/400 per §5, and the `attach_policy` version bump.

## Step 7: Run tests and iterate — 2026-09-04T04:57:00.000Z

All 8 parallel rounds are green: `passed=425 failed=0 errors=0 skipped=0 total=425` in every round.

## Summary

**Iterations run:** 2 (sweep 1 diagnosed, fixes applied, sweep 2 confirmed clean). Sweep 1 was bit-identical across all 8 rounds at 408/425 — zero flakiness, so no failure was host-load noise and every one was a real defect.

**Tests deleted:** none. No failure traced to PRD silence.

**Fixes applied to `test_helpers/`:** none. The failures localized to `test_suite/`; the one helper-shaped bug was in a private helper method living inside the test file itself (`_legal_agreement_payload`), not in `test_helpers/`.

**Fixes applied to `implementation/`:** none. Zero implementation changes were warranted. I specifically verified the four behaviours the failing tests appeared to indict and each is PRD-faithful: `routes_servicing.py::post_payment` (body-schema `received_date` check fires before the ACTIVE-status gate, matching §2.10 priority 7 before 11), `routes_admin.py::set_clock` (three-fractional-digit `current_utc` echo), `routes_endorsements.py` (absent `expected_agreement_version` → `ERR_INVALID_REQUEST` at HTTP 400, which is what §5 lists), and `routes_agreements.py::attach_policy` (version bump per PRD line 207).

**Fixes applied to `test_suite/`** — 17 tests, all test-side defects in three families:

*Family 1 — hardcoded version totals that denied the PRD-207 attachment bump* (PRD line 207: attachment "increments the agreement's `policy_count` and advances the agreement's `version`"). `test_11_corner_state_machines.py`: `test_the_provisional_quote_is_written_in_full` 2→3; `test_the_opening_balances_are_the_quote_and_nothing_else` 3→4; `test_the_void_writes_the_terminal_state_and_advances_the_version` 3→4; `test_the_four_refusals_left_the_terminal_row_untouched` 3→4.

*Family 2 — setups that tripped a higher §2.10 priority than the one asserted.* `test_a_refused_submit_writes_no_provisional_quote`: suspended the agency before the empty-note submit, so priority 23 `ERR_AGENT_SUSPENDED` masked priority 29 `ERR_NO_FINANCED_POLICIES` — moved the suspension after that assertion. Both `TestVoidedAgreementRefusesEveryTrigger` payment probes used `received_date` 2026-10-01 against a 2026-08-15 clock, which PRD line 263 refuses, so priority 7 masked priority 11 — moved to 2026-08-15. `test_13::test_both_malformed_policy_terms_share_one_code` attached onto a PENDING_VERIFICATION note, so priority 11 masked priority 31 — added a `_drafted` helper and attach onto a DRAFT note.

*Family 3 — bugs in the tests' own preconditions.* Five tests in `TestActivationWritesScheduleBalancesAndActivatedAt` asserted `quote_basis == "PROVISIONAL"` against `bundle["agreement"]` (the DRAFT create response, whose basis PRD line 203 nulls) instead of `bundle["submitted"]`. `test_12::test_the_first_period_tie_is_carried_up` had an arithmetic error in its own tie identity (905,400,000 vs 452,760,000) — now `(3772 * 2 + 1) * 120000`. `_legal_agreement_payload` in `test_13` passed `first_installment_due_date` as a fixed keyword, raising `TypeError` in two tests that override it — now merged as a default. `test_17::test_the_expected_version_is_mandatory_rather_than_optional` expected HTTP 422 where PRD §5 lists `ERR_INVALID_REQUEST` at 400. `test_17::test_activation_is_complete_when_it_returns` compared `activated_at` to a bare-`Z` string where §2.4/§2.2 mandate three fractional digits.

**One assertion narrowed (STEP 1c partial coverage, not a deletion):** `test_13::test_one_day_of_clock_rewind_has_its_own_code` pinned `current_utc` to the exact byte string `"2026-08-15T00:00:00Z"`. The monotonicity rule and the acceptance of an equal instant are verbatim-covered and both kept, including `ERR_CLOCK_REWIND`/422; but the fractional-digit serialization of `current_utc` is not uniquely derivable — PRD line 90 writes the epoch bare-`Z` while §2.2/§2.4 mandate three digits, and both readings are defensible. The compare is now instant-level via a local `_as_instant` parser, keeping the covered assertion and dropping only the uncovered format pin.

**Orchestrator verification (independent of the subagent's claim):** all 8 `workspace/implementation/results.{1..8}.json` exist on disk (~135 KB each, same mtime 04:57) and each parses to `passed=425 failed=0 errors=0 skipped=0 total=425`. Sweep artifacts confirmed real.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 17 `test_suite/` fixes and one STEP-1c narrowing, so the skip condition (zero fixes of any kind) does not hold. Although `implementation/` was unchanged, the narrowing and several of the fix families localize genuine PRD-side ambiguity (the `current_utc` / timestamp fractional-digit conflict between PRD line 90 and §2.2/§2.4; the DRAFT-create `quote_basis` nulling; the HTTP status attached to a missing OCC field), which is exactly what Step 8 exists to pin.

## Step 8: Finalize PRD — 2026-09-04T05:12:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both traceable to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 438 lines / 14,262 words
- `PRD_FINALIZED.md`: 438 lines / 14,355 words
- Delta: **0.0% by line, +0.65% by word** (+93 words, two in-place paragraph edits, no new sections)

## Changes

- **§2.4 (Common Resource Properties and Row Versions)** — insert — pins the serialization of every non-`created_at`/`updated_at` instant field (`activated_at`, `financed_at`, `reversed_at`, `current_utc`) to the same three-fractional-digit ISO 8601 UTC form, notes it applies only when non-null, and states that calendar-date fields stay plain `YYYY-MM-DD`. Also disambiguated the following sentence's "Both fields" → "Both `updated_at` and `version`" since a sentence now sits between. — `implementation/core.py:118` (`fmt_dt`), `routes_admin.py:240`, `routes_agreements.py:436`, `routes_endorsements.py:112,212`, `routes_servicing.py:96`
- **§2.10 priority 7** — revise — adds "a payment's `received_date` no later than the clock date" to the priority-7 body-schema list and states explicitly that a future `received_date` reports `ERR_INVALID_REQUEST` ahead of the priority-11 financing-status gate. — `implementation/routes_servicing.py:40-42` (fires before `require_status` at line 42)

## Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp serialization**
- (a) Subject: the wire format of instant-valued response fields, and by exclusion of date-valued ones.
- (b) Paths enumerated: grepped `now_iso|fmt_dt|clock.date()` across all of `implementation/`. Single formatter `core.fmt_dt` (always UTC, always 3 digits) reached by `Clock.now_iso`; consumers: `core.new_record` (`created_at`), `core.touch` (`updated_at`), `core._meta` (`api_request_timestamp`), `routes_agreements.py:436` (`activated_at` on activate), `routes_endorsements.py:212` (`activated_at` on the restructure successor — the second, non-Step-7 callsite), `routes_endorsements.py:112` (`financed_at`), `routes_servicing.py:96` (`reversed_at`), `routes_admin.py:240` (`current_utc`). Also read all of `model.py`'s serializers to confirm the instant-field set is exactly {created_at, updated_at, activated_at, financed_at, reversed_at} and that every remaining date-shaped field (`issued_date`, `cured_date`, `executed_date`, `assessed_date`, `received_date`, `requested_date`, `cancellation_effective_date`, `effective_cancel_date`, `due_date`, `verified_effective_date`, `corrected_effective_date`, license window dates) is stored via `date.isoformat()` and so is `YYYY-MM-DD`.
- (c) Adjustments made: added "whenever it is not null" because all three of `activated_at`, `financed_at`, `reversed_at` are initialized to `None` and stay null on non-activated / non-financed / non-reversed rows; added the closing clause about calendar-date fields so the new sentence cannot be read as sweeping the date-only fields into the timestamp format; enumerated the four fields explicitly rather than saying "every timestamp", so the claim stays checkable against the enumerated callsites.

**Edit 2 — §2.10 priority 7 `received_date`**
- (a) Subject: the `received_date` <= clock-date rule on payment posting — its error identifier and its rank in the precedence order.
- (b) Paths enumerated: `routes_servicing.py:31-47` `post_payment` in full (ownership at :33 runs before `body()` at :36, matching priority 5 before 7; `amount_cents`/`received_date`/`method` schema checks at :37-39; the clock comparison at :40-41 raising `ERR_INVALID_REQUEST`; `require_status` at :42; `ERR_PAYMENT_EXCEEDS_PAYOFF` at :44). Grepped every other body-date-versus-clock comparison in `implementation/`: `gates.require_first_due_window` (`first_installment_due_date`, its own code `ERR_INVALID_FIRST_DUE_DATE` at priority 33, and the opposite direction — must be strictly *after* the clock), `routes_endorsements.py:38-44` (endorsement `effective_date` floored at `verified_effective_date`, `ERR_INVALID_REQUEST`, no clock involved), `routes_servicing.py:391` (`posted_date` on a carrier return — well-formedness only, no clock comparison). Also confirmed `ERR_INVALID_REQUEST` → 400 in `core.ERROR_STATUS` matches §5.
- (c) Adjustments made: scoped the clause to "a payment's `received_date`" rather than any general "body dates not in the future" rule, because `first_installment_due_date` must be in the future and carries a different code at a different priority, and `posted_date` is not clock-checked at all. Phrased the second sentence as "would fail the gate at priority 11" rather than naming a specific status, so it stays true for every terminal and non-`ACTIVE` status the gate refuses.

**Items deliberately not patched** (PRD already uniquely determines them; the Step 7 fixes were test-side defects): the attachment `version` bump (PRD line 207, verified against `routes_agreements.py` attach + `core.touch`'s once-per-request semantics, which reproduces the 1/2/3/4 create-attach-submit-activate ladder the tests now assert); the §2.10 masking cases (23 over 29, 11 over 31, 11 over 39); `quote_basis` null on the DRAFT create response (line 203, `blank_agreement_fields`); the missing `expected_agreement_version` → `ERR_INVALID_REQUEST`/400 (§2.8 mandatory + priority 7 + §5, verified at `routes_endorsements.py:92`); and the test_12 tie arithmetic and `_legal_agreement_payload` `TypeError`, which are pure fixture bugs.

## Step 9: Complete PRD — 2026-09-04T05:45:00.000Z

Step 9 was deliberately run as THREE sequential file-partitioned passes rather than one subagent, because a single-pass whole-implementation scan has previously produced a `PRD_COMPLETED.md` byte-identical to its source (i.e. the scan silently never ran). Partition: pass 1 = `core.py`/`model.py`/`gates.py`/`app.py`; pass 2 = `calc.py`/`routes_admin.py`/`routes_agreements.py`; pass 3 = `routes_servicing.py`/`routes_endorsements.py`. Each pass was told the prior passes' confirmed-pinned behaviors so no surface was audited twice and none was skipped; only pass 1 performed the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 edited in place.

### Pass 1 — core.py / model.py / gates.py / app.py
438 lines / 103,431 chars → 439 lines / 105,962 chars. 9 ambiguity-pins, 1 mismatch-revision (10 hunks).
- 2.1 RBAC — revise — ambiguity — `ERR_UNAUTHENTICATED` also fires on a whitespace-only `X-User-ID`/`X-User-Role` — `core.py:248`
- 2.2 Success envelope — revise — ambiguity — `api_request_id` is `req_` plus exactly twenty random uppercase-letter/digit characters — `core.py:158-160`
- 2.2 Success envelope — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `core.py:198-205`
- 2.2 Error envelope — insert — ambiguity — serving-layer failures report `ERR_INVALID_REQUEST` under the routing status (404 unroutable path, 405 bad method, other 4xx keeps status, 500 unexpected); trailing-slash variants resolve to the same operation — `app.py:21,37-56`
- 2.3 Pagination — insert — ambiguity — rows sharing a `created_at` are tie-broken by creation sequence, everywhere `created_at` ordering applies — `core.py:190-191`
- 2.4 Row Versions — revise — **mismatch** — `version` advances by exactly 1 per mutating *request*, not once per effect — `core.py:174-187`, `app.py:29-31`
- 2.10 rule 7 — insert — ambiguity — a present-but-non-JSON-object body is `ERR_INVALID_REQUEST`; an absent body is read as an empty object and judged against the schema — `core.py:272-280`
- 3.2 — insert — ambiguity — `policy_count`/`verified_policy_count` are derived on read from current policy statuses, not stored counters — `model.py:167-175`
- 3.2 — insert — ambiguity — the service-fee ceiling is `approved_service_fee_cap_cents` only when the exception is approved *and* that field is non-null; a rate-only exception leaves `max_service_fee_cents` in force — `gates.py:69-82`
- 3.6 — insert — ambiguity — installments swept to `PAID` also have `paid_cents` raised to `amount_cents`, booked as the payment's contribution so reversal unwinds it — `gates.py:121-129`

Confirmed already-pinned by pass 1 (not re-audited later): error-id→HTTP status table (53/53), `ApiError`/`fail` semantics, clock epoch `2026-08-01T00:00:00Z` and `fmt_dt`, `new_record` id/created_at/updated_at/version=1 plus the unversioned verification rows, both envelope shapes, list `meta` fields, five role names and authenticate-then-authorize ordering, pagination defaults 10/1..100/offset>=0, `round_half_up` ties-away-from-zero, `add_months` day-clamping, strict `YYYY-MM-DD` and 2-letter state codes, all path-lookup 404 codes, `license_is_effective`/`state_is_licensed`, `active_agreement_count`/`outstanding_chargeback_cents`/`endorsed_premium_cents` derivations, every serializer field set, the three state-gate codes, `ERR_STATE_NOT_LICENSED`/`ERR_AGENT_SUSPENDED`/`ERR_TERM_EXCEEDS_STATE_MAXIMUM`, first-due window (strictly after clock, <=60 days, 60 accepted), min-down-payment bps comparison with equality passing, 2500 bps premium variance, the cure predicate and notice `CURED` cascade, paid-in-full trigger and `refund_due_cents`, `has_outstanding_fee` as notice precondition.

### Pass 2 — calc.py / routes_admin.py / routes_agreements.py
439 lines / 105,962 chars → 439 lines / 111,102 chars. 16 ambiguity-pins, 4 mismatch-revisions (30 cumulative hunks). Pass 1's 10 edits verified untouched.
- 2.5 — insert — ambiguity — `to_iso8601` accepted grammar (T or space separator, optional seconds, 1–6 fractional digits, `Z`/`±HH:MM`/`±HHMM` offset converted to UTC, absent offset read as UTC; malformed → `ERR_INVALID_REQUEST`); `current_utc` echoes normalized to UTC — `routes_admin.py:200-240`
- 2.7 — insert — ambiguity — mandatory body FKs absent/null/non-blank-string give `ERR_INVALID_REQUEST`, not 404; the optional coherence `agreement_id` is ignored when absent/null, else looked up (404) — `routes_agreements.py:29-35,277-278`
- 2.9 — insert — ambiguity — inverted `late_fee_min`/`late_fee_max` band is `ERR_INVALID_REQUEST` (400) — `routes_admin.py:36-38`
- 2.9 — insert — ambiguity — duplicate `license_number` within a regime, and a non-strictly-later expiration, are both `ERR_INVALID_REQUEST` (400) — `routes_admin.py:86-92`
- 3.1 — insert — ambiguity — suspending an already-`SUSPENDED` license → `ERR_INVALID_REQUEST` (400) — `routes_admin.py:120-121`
- 3.1 — insert — ambiguity — duplicate `naic_code` → `ERR_INVALID_REQUEST` (400) — `routes_admin.py:191-194`
- 3.1 — revise — **mismatch** — agency-suspension `reason` accepted as a string but persisted on no field; re-suspending → `ERR_INVALID_REQUEST` (400) — `routes_admin.py:174-179`
- 3.2 — revise — **mismatch** — both rate-exception overrides are optional; an approval supplying neither still sets `rate_exception_approved` with both caps null; each override is a non-negative integer — `routes_agreements.py:486-505`
- 3.2 — revise — ambiguity — submission's min-down-payment basis is the provisional engine basis: `gross_premium_cents` over `PENDING_VERIFICATION`, non-`carried_over` policies — `routes_agreements.py:398`, `calc.py:29-40`
- 3.2 — revise — **mismatch** — void `reason` accepted but not persisted; *any* `Payment` row (a `REVERSED` one included) blocks the void, refusal `ERR_AGREEMENT_STATE_INVALID` (409) — `routes_agreements.py:447-452`
- 3.3 — insert — ambiguity — the coherence agreement is named by an *optional* `agreement_id` on the filing; omitting it skips the check — `routes_agreements.py:276-278,304-307`
- 3.3 — insert — ambiguity — on reopen-verification the policy's `DISPUTED` gate is tested *before* the note's status gate — `routes_agreements.py:363-364`
- 3.4 — revise — ambiguity — activation's min-down-payment basis is the final engine basis: `financed_premium_cents` over `VERIFIED`, non-`carried_over` policies — `routes_agreements.py:422`, `calc.py:29-40`
- 3.6 — insert — ambiguity — all payoff-quote figures read current balances; `as_of_date` is echoed only — `routes_agreements.py:510-523`, `calc.py:202-215`
- 3.6 — revise — ambiguity — the rebate is capped at `unpaid_finance_charge_cents` then floored at zero, in that order — `calc.py:195-199`
- 3.6 — revise — ambiguity — `applied_unapplied_cents` is added to `unapplied_credit_cents` (reducing it when negative); payoff installments have `paid_cents` raised to `amount_cents` as this payment's contribution — `calc.py:262-270`
- 3.6 — revise — ambiguity — bucket one continues to the next fee after skipping an unaffordable one, so a later smaller fee is still settled; only after every fee is considered does the remainder reach bucket two — `calc.py:281-288`
- 3.6 — revise — **mismatch** — reversal only returns fees still in `PAID`; installment `paid_cents` floors at zero and status is re-derived (`VOIDED` stays `VOIDED`, still-fully-paid stays `PAID`, else `PAST_DUE`/`SCHEDULED` by due date) — `calc.py:333-355`
- 3.7 — insert — ambiguity — a term length of zero days or fewer yields an estimate of zero instead of a division, while `earned_days` is still stamped — `calc.py:388-390`
- 3.9 — revise — ambiguity — tail redistribution pinned in full: tail total = new `total_of_payments_cents` less `paid_cents` across every installment (frozen included); level `ADD_ON` discipline regardless of `finance_charge_method`; tail finance charge = new `finance_charge_cents` less frozen `finance_charge_component_cents`, half-up shares with the exact remainder on the last tail row; principal = amount − charge; due dates/numbers untouched; empty tail is a no-op — `calc.py:150-175`

Confirmed already-pinned by pass 2: volume tiers 1800/1500/1200 at the 500000/2000000 boundaries; `amount_financed`; rate = min(approved-or-tier, ceiling); ADD_ON one-shot charge vs SIMPLE_INTEREST declining accrual and both installment shapes; `add_months` due-date walk; provisional vs final basis; both rebate formulas incl. `VOIDED` exclusion and r<=0→0; `payoff_figures` field set and `net_payoff`; PAYOFF/STANDARD threshold; outstanding-fee sort order; buckets 2/3 orderings and charge-before-principal; `paid_cents`-reaches-`amount_cents`→`PAID`; late-fee round-then-clamp; earned-days clamping and `fully_earned`→0; pro-rata then short-rate penalty on the rounded pro-rata; cancellation-fee tiers 0/2500/5000 at 25000; residual; `CLOSED_ZERO` vs `CANCELLED_DEFICIENT`; `refund_due_cents = -residual`; COMMISSION_CAPPED/RESERVE_CAPPED caps; chargeback row field set; cap-breach suspension on post-insert exposure; every `StateRateRule`/`ProducerAgent` numeric range; `license_required` default true; license `ACTIVE` on creation and derived `is_effective`; license `status` filter; insured/insurer/agent field sets and 201s; clock monotonicity with equality accepted; creation gate order and the `DRAFT`/`CURRENT` zeroed stamp; policy-attachment schema, 730-day/`min_earned_days` shape, global half-open overlap scan; list filter sets; the whole verification surface (standing, decision enum, `CORRECTED` required/forbidden fields, derived `party` fields, one-live-voice rule, pair evaluation, `dispute_reason` precedence, dispute→`DRAFT` cascade, superseded rows still listed); submit's eight preconditions in priority order; activation's `verified_policy_count == policy_count >= 1`, repricing, schedule cut, balance seeding, `activated_at`; void cascade to `CANCELLED` policies with null `cancellation_effective_date`; installment ordering and `status` filter; rate-exception SOD-before-status ordering and the two ceiling checks.

### Pass 3 — routes_servicing.py / routes_endorsements.py
439 lines / 111,102 chars → 439 lines / 117,906 chars. 18 ambiguity-pins, 10 mismatch-revisions (51 cumulative hunks, 204 diff lines). All 30 prior edits verified intact.
Ambiguity-pins:
- §2.3 — list filter values are compared as opaque strings and never validated against the resource enum, so an out-of-enum `status`/`party` yields an empty page — `routes_servicing.py:77`, `routes_endorsements.py:64`
- §2.7 — on the carrier-cancellation-request listing the `policy_id` is resolved (404) only when `agreement_id` accompanies it; alone it is a pure filter — `routes_servicing.py:353`
- §2.8 — both expected-version fields must be positive integers; shape failure precedes the 412 — `routes_endorsements.py:92,248`
- §2.10 #7 — operations defining no input field never inspect the body — `routes_servicing.py:146,213,271`
- §3.5 — defines all three servicing-run counts and that one run = one request for `version` purposes — `routes_servicing.py:200`
- §3.5 — waiver `justification` is non-empty but stored nowhere; no note status/stage gates the waiver — `routes_servicing.py:131`
- §3.7 — blackout anchors on the last-created `CURED` notice and uses the regime's live `noic_notice_days` — `routes_servicing.py:226`
- §3.7 — full execution gate order + notice selection (last-created `ISSUED`, else last of any status); SoD only when an `ISSUED` notice exists — `routes_servicing.py:274`
- §3.7 — a partly paid `SCHEDULED` installment stays `SCHEDULED` — `routes_servicing.py:328`
- §3.7 — execution payload is those four integers, HTTP 200, financing status untouched — `routes_servicing.py:333`
- §3.8 — `posted_date` mandatory/well-formed but not clock-compared and stored nowhere — `routes_servicing.py:391`
- §3.8 — no `LateFeeAssessment` row changes status when the carrier credit retires `late_fee_balance_cents` — `routes_servicing.py:413`
- §3.8 — the agency's `version` advances only when the offset also moves its `status` — `routes_endorsements.py:261,271`
- §3.8 — neither chargeback surface is narrowed by ownership — `routes_endorsements.py:223`
- §3.9 — only `PENDING` endorsements on `VERIFIED` policies are financed, on one shared clock instant — `routes_endorsements.py:100`
- §3.9 — the restructure down-payment re-test runs against a basis of zero and can never refuse — `routes_endorsements.py:145`
- §3.9 — the predecessor's `unapplied_credit_cents`, `late_fee_count`, `refund_due_cents` etc. are left untouched — `routes_endorsements.py:180`
- §3.9 — the successor is returned with `version` 1 — `routes_endorsements.py:201`
Mismatch-revisions:
- §2.10 #20 — the coherence pair and its `policy_id` lookup precede the `limit`/`offset` checks of priority 7 — `routes_servicing.py:353,364`
- §2.10 #30 — `ERR_POLICY_NOT_VERIFIED` also guards cancellation execution, tested after priority 36 — `routes_servicing.py:291`
- §3.5 — waiver cure condition is `late_fee_balance_cents == 0`, not "no `OUTSTANDING` fee" — `gates.py:100`
- §3.6 — the overpayment ceiling's net payoff is date-independent; `received_date` never enters it — `routes_servicing.py:43`
- §3.6 — same for the `PAYOFF`/`STANDARD` variant choice — `calc.py:239`
- §3.6 — re-delinquency is judged after `PAID_IN_FULL`→`ACTIVE`, only out of `CURRENT`, with no stage gate — `routes_servicing.py:98`
- §3.7 — the snapshot governs `effective_cancel_date` and the notice-period gate; the blackout uses the regime's live value — `routes_servicing.py:229`
- §3.9 — the endorsement `effective_date` floor applies only when `verified_effective_date` is non-null, fails with `ERR_INVALID_REQUEST`, and is checked after the policy-state gate — `routes_endorsements.py:37`
- §3.9 — decline `reason` is accepted but kept on no field — `routes_endorsements.py:76`
- §3.9 — `carried_over_balance_cents` uses the `PAST_DUE` unpaid remainders plus `late_fee_balance_cents` less `unapplied_credit_cents` — `routes_endorsements.py:161`

### Step 9 totals and orchestrator verification
- Source `PRD_FINALIZED.md` 438 lines / 103,431 chars → `PRD_COMPLETED.md` 439 lines / 117,906 chars (**+1 line, +14,475 chars, +14.0%**).
- **43 ambiguity-pins, 15 mismatch-revisions** across 51 diff hunks; every hunk an in-paragraph insert or revision, zero new sections (heading count unchanged at 28).
- Orchestrator-side check: `diff PRD_FINALIZED.md PRD_COMPLETED.md | grep -c '^[0-9]'` = 51 (non-zero, so the scan genuinely ran and is not a byte-identical copy), `tail -3` ends at `| ERR_OFFSET_EXCEEDS_RESERVE | 422 |` — a real section boundary — and all 28 headings survive. No truncation.

## Pipeline complete — 2026-09-04T05:47:00.000Z

Steps 1–9 all executed. Final state: 3 scaffold files, `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `test_helpers/` (9 files, 2,912 lines), `test_suite/` (18 files, 425 tests), `workspace/implementation/` (11 files) and `workspace/implementation/results.{1..8}.json` all at 425/425.
