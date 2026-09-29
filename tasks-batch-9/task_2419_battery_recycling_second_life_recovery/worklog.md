# Worklog — task_2419_battery_recycling_second_life_recovery

## Step 1: Create task directory — 2026-09-02T15:48:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery` and its `workspace/` subdirectory. Index pre-assigned by the orchestration prompt (2419); no scan of ./tasks/ performed, per instructions (32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-02T17:36:00.000Z

Scaffold generation for **task_2419_battery_recycling_second_life_recovery** is complete and lint-clean.

Files written to `/home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/`:
- `SCAFFOLD.yaml` (§1.0–§1.7, 2,765 lines) — no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key, 2,823 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key, 4,469 lines)

Lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     15
  §1.8 instances scanned:     27
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1365

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Worklog summary:
- **Surface (§1.0–§1.7):** api_prefix `/recycling`; 15 entities, 63 endpoints, 62 error codes, 10 roles (incl. `SupplierRep` as `entity_backed:Supplier`), 9 calculation rules, 13 validation priorities, 2 OCC concurrency rules, 3 invariants. complexity_profile: layers `dual_variant_calculation` / `cascading_side_effects` / `optimistic_concurrency` / `derived_field_reconciliation`, topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.
- **§1.8 difficulty design:** 9 rule blocks / **27 instances** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 4, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3.
- **§1.9 corner design:** 9 sections / **87 instances** (63 with full `test_recipe`, 24 `excluded_because` stubs citing §1.8) — entities 12, state_machines 19, calculations 14, validations 13, endpoints 9, errors 9, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1.
- **Consistency checks passed:** instance names unique across both design files (0 duplicates); all 24 stub citations resolve to real §1.8 `rule_id / name` pairs; 0 unbound `${...}` placeholders across all 1,365 calls; all 62 error codes triggerable across §1.8+§1.9 (8 only in §1.8, the rest in §1.9); claim types drawn solely from the claim-extraction-guide taxonomy.
- **One SCAFFOLD.yaml fix during lint:** three sub-resource list GETs (`/intakes/{id}/manifests`, `/modules/{id}/triage-decisions`, `/lots/{id}/recovery-outputs`) had to use the SKILL §1.5 canonical `{id}` parent placeholder for check (f) to recognize them as reverse-reachability channels for `HazmatManifest.intake_id`, `TriageDecision.module_id` and `RecoveryOutput.lot_id`. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-02T17:36:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:48:00.000Z

Done. PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/workspace/PRD.md`.

**Output:** 420 lines. Last section heading: `## 5. Error Code Catalogue`; file ends at the final error-table row (`| ERR_SUPPLIER_CREDIT_HOLD | 402 |`) — a real section boundary, no mid-sentence truncation, no leftover build markers.

**Structure:** §1 Introduction (3 paragraphs, ledger + pricing-engine framing); §2 with 11 domain-derived subsections (roles/RBAC, verbatim response envelope, pagination & list ordering, identity/versioning, logical clock, nested path resolution, 13-tier validation precedence, OCC, mass/money precision, ledger invariants, cascade semantics); §3 with 9 lifecycle-ordered subsections (network config & price feed → custody & capacity projection → hazmat manifests & quarantine cascade → dismantling/triage scoring → release & provisional payable → campaign scheduling → charging/assay/finalization → certification & discharge compliance → payable ledger); §4 endpoint table (4 columns, 63 rows); §5 error table (2 columns, 62 rows).

**Hard Contracts — all PASS (verified with a script against the scaffold, not by eye):**

```
Field coverage check:
- entities[].fields: 123 required, 123 present, 0 missing
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params/path_params: 25 required, 25 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 14 checked (13 tiers, two rules sharing priority 3), 14 expressed as an explicit ordered list in §2.7, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /recycling/intakes/{intake_id}/modules + expected_intake_version + ERR_STALE_INTAKE_VERSION/412; POST /recycling/lots/{lot_id}/charge + expected_lot_version + ERR_STALE_LOT_VERSION/412), 0 missing
- state_machines[].transitions: 40 checked across 7 machines (Intake custody 11, Intake compliance 4, Module 8, Campaign 3, Lot 4, Settlement 6, Permit 2, DischargeEvent 1, Passport 1), 40 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed in prose (no operator syntax, no fuzzy words), 0 missing
- validations[] conditions: 62 error ids checked, 62 matchable to a condition in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 63 endpoints checked, all cascades and applies_to scopes enumerated, 0 missing
- entities[].fields[] structured content: 123 checked (types, defaults, initial values, common_fields=false exposure for MetalIndexPrice and RecoveryOutput), 123 reconstructible, 0 missing
- sibling-branch symmetry: 4 groups checked (three triage dispositions; lot void from OPEN vs CHARGED; the three credit-hold-release paths settle/void/apply-umpire; PROVISIONAL vs FINAL pricing variants), 4 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1001
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was diffed against `section-2.2-response-structure.md` and matches byte-for-byte. Per instructions, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

Two notes for downstream: (1) the scaffold's `RecoveryLot.charge` precondition list puts the `status == OPEN` check before the version check, but `validations[]` priority puts OCC (7) ahead of state (8) — the PRD follows the priority table and says so explicitly in §3.7; (2) 63 endpoints are present in the table even though `difficulty_level` comments say 62, matching the actual `endpoints[]` array.

**Orchestrator anti-truncation verification (independent of subagent claim):** `wc -l` = 420; `tail -20` ends at the `ERR_SUPPLIER_CREDIT_HOLD | 402` table row; heading scan confirms §1 → §2 (11 subsections) → §3 (9 subsections) → §4 → §5 all present in order. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-02T18:48:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message per the skill; Step 6 returned first and is recorded first. Step 5's entry follows.)

The implementation is complete and verified end to end.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/workspace/implementation/`
- `start.sh` (executable, installs Flask only if missing, then `exec python3 app.py` on `$PORT`, default 10000)
- `app.py` — app factory, four blueprints, envelope-shaped handlers for `ApiError` / `HTTPException` / unexpected errors
- `core.py` — in-memory `Store` (15 dicts) + `db`, logical clock, Decimal quantizers (`q0/q2/q3/q4`, ROUND_HALF_UP), ISO-8601 formatting (exactly 3 ms digits + `Z`), envelope builders, 63-entry `ERROR_STATUS` map, auth/role decorator, field validators, pagination
- `calc.py` — global constants + all 9 calculations
- `services.py` — path resolvers, aggregate recomputation, settlement pricing, cascades
- `routes_config.py` (17), `routes_intake.py` (17), `routes_recovery.py` (21), `routes_settlement.py` (8)
- `requirements.txt` — `flask`

## Endpoint coverage
Programmatically diffed the registered URL map against the SCAFFOLD `endpoints` table: **63 vs 63, zero missing, zero extra** (Flask's `/static` rule excluded).

## Verification performed
Three driver scripts against a live `start.sh` server, all green:
- Golden vectors: PROVISIONAL 800 kg NMC622 → gross 260224 / fee 31227 / qd 0.02→5204 / pre 223793 / hazmat 7300 / net 216493; FINAL after finalize → lines 83302/63006/89100/21600, gross 257008, net 213727, `max_variance_pp` 3.50, `mass_balance_pct` exactly 97.00; capacity projection → baseline 100.000, projected 2084.000, first_deficit_day 13, date 2026-09-14, deficit 0.200, no writes.
- Cascades and edges: mislabel + both component caps + 3-strike 1.5× escalation clamped to 0.2000; hazmat cap branch; LFP zero-factor metals (`line_cents` 0, `unit_price_cents_per_kg` null, no lookup); missing quote at release leaves no state (intake still PACKAGED, zero settlements); manifest reject 4-link cascade + revision-2 resubmission; credit-hold quarantine and its release on settle; lot void unwind + campaign bubble-up CLOSE; permit daily buckets, window exclusion, void recompute, lazy expiry; passport floor / duplicate code / already-issued / revoke; both OCC guards; segregation of duties; `ERR_NOT_OWNER`; 3-round dispute→umpire→apply cycle then `ERR_DISPUTE_ROUNDS_EXHAUSTED`; ledger reversals back to zero.
- Isolation: fresh boot in ~0.7 s with all 15 collections empty and the clock at the default `2026-08-01T00:00:00.000Z`; no persistence primitives anywhere (grep for sqlite/open/pickle/json.dump//tmp → none).

Two apparent mismatches during testing were my test expectations, not the server: an arithmetic slip in my hand-summed gross (325280 is correct), and `max_variance_pp` = 8.00 where a lot had only an NI assay line — the spec takes the max across all four payable metals, so a declared-but-unrecovered CU at 8.00 pp legitimately dominates.

## Notable design decisions
- Release prices the cascade settlement **before** mutating the intake, so `ERR_INDEX_PRICE_UNAVAILABLE` leaves nothing behind; the child is absent from the release body and discoverable only via `GET /recycling/settlements?intake_id=`.
- Finalize snapshots each supplier's `quality_strike_count` before adding strikes, so the deduction never observes its own side effect.
- `settlement["_lot_id"]` (underscore-prefixed, stripped by `serialize()`) links a settlement to its contributing lot for umpire re-pricing.
- Validation order follows PRD §2.7's thirteen tiers over §3.x narrative order (campaign create: window conflict → buffer → capacity → family; charge: OCC → state → exceeds-plan → intake/chemistry), with finalize keeping its own §3.7 sequence.
- Apply-umpire does not clear `umpire_metal` / `umpire_contained_kg` (the scaffold's explicit side-effect list omits it); `posted_amount_cents` is preserved on settle and zeroed on apply-umpire/void.
- Voiding a terminal lot returns `ERR_LOT_NOT_OPEN`; a passport on a non-finalized lot returns `ERR_RECYCLED_CONTENT_BELOW_MINIMUM`; a dispute on a PROVISIONAL settlement returns `ERR_VARIANCE_WITHIN_TOLERANCE` (no dedicated codes exist for these).

## Step 5: Generate unit tests — 2026-09-02T19:39:00.000Z

Test generation for task 2419 is complete.

## Files written

`workspace/test_helpers/` (9 files): `__init__.py`, `types.py`, `constants.py`, `test_users.py`, `api_errors.py`, `api_client.py`, `factories.py`, `fixtures.py`, `assertions.py`.

`workspace/test_suite/` (19 files): `conftest.py` plus `test_01_settlement_pricing_waterfall.py` (8), `test_02_triage_scoring_and_fork.py` (4), `test_03_parallel_and_cyclic_state_machines.py` (6), `test_04_transitive_cascades.py` (7), `test_05_validation_precedence.py` (8), `test_06_boundary_precision.py` (6), `test_07_cross_entity_state_dependency.py` (6), `test_08_resource_temporal_overlap.py` (6), `test_09_compensating_invariants.py` (7), `test_10_entities.py` (12), `test_11_state_machines.py` (11), `test_12_calculations.py` (6), `test_13_validations.py` (10), `test_14_endpoints.py` (9), `test_15_errors.py` (7), `test_16_rbac.py` (5), `test_17_cross_cutting.py` (2), `test_18_consistency.py` (1).

Nothing under `workspace/implementation/` was read or written at any point.

## Coverage

- **121 tests total** — 58 queue A, 63 queue B.
- Queue A: all **27** difficulty instances covered, every one with **>= 2** tests.
- Queue B: all **63** non-stub corner instances covered with **>= 1** test each; the 24 `excluded_because:` stubs were not translated.
- Every test carries exactly one `Design:` line as the last line of its docstring; audit reports 0 tag problems, no duplicate tags, no tags pointing at stubs or non-existent instances.
- Every test cites at least one byte-verbatim PRD sentence: 134 quoted sentences checked, **0 misses**.
- No `skip`, `xfail`, `TODO` or placeholder anywhere; no mention of the scaffold or its section numbers; all modules byte-compile.

## Instances skipped

None. All 27 difficulty instances and all 63 non-stub corner instances passed the PRD-first two-condition filter.

## Design expectations corrected against the PRD

Three design assertions were not uniquely derivable from the PRD as written, so the tests assert what the PRD actually mandates:

1. `Corner/cross_cutting_complexity_layers/stale_expected_intake_version_blocks_the_second_module_write` — the design expects a module create carrying **both** a duplicate `serial_code` and a stale `expected_intake_version` to return 412 `ERR_STALE_INTAKE_VERSION`. PRD §2.7 puts serial-code uniqueness in tier 4 (`ERR_INVALID_REQUEST`, 400) and OCC in tier 7, and the first failing tier wins, so the test asserts **400**.
2. `Corner/rbac/assay_technician_cannot_post_the_settlement_its_yields_priced` — the design asserts a `CHARGED` lot has `recovered_mass_kg == null`; PRD §3.6 says a new lot starts at 0.0, so the test asserts **0.0**.
3. `Corner/consistency_model/every_write_is_visible_to_the_immediately_following_read` — the design asserts the cascade-created PROVISIONAL settlement has `net_payable_cents == 28090`. PRD §3.5 applies the nominal recovery factor to PROVISIONAL (28090 is the FINAL figure, recovery factor 1.0), giving gross 31920 → net **26685**, which is what the test asserts. The corner design makes this same PROVISIONAL/FINAL arithmetic slip in several places; every affected test uses the PRD-derived figure.

One rationale was also strengthened: in `Corner/rbac/foreign_roles_are_forbidden_on_other_roles_exclusive_operations` the design's self-close attempt used a PlantOperator id differing from the submitter, so the segregation-of-duties check could never have fired; the test sends the submitter's own id under the PlantOperator role, so tiers 2 and 3 would both fail and tier 2 demonstrably wins.

**Orchestrator post-step correction (layout) [Step 5]:** the generator wrote `test_helpers/` and `test_suite/` under `workspace/` instead of the task root that the skill's Output layout declares. Verified no file in either directory references a `workspace` path (`grep -rn workspace` → 0 hits), removed stale `__pycache__`, then moved both directories together to the task root: `tasks/task_2419_.../test_helpers` and `tasks/task_2419_.../test_suite`. They remain siblings, which is what `executor.py:134` requires — the runner puts `Path(test_dir).parent` on `sys.path` so `from test_helpers import ...` resolves. Confirmed after the move: 19 files in `test_suite/`, 9 in `test_helpers/`, 121 `def test_` functions.

## Step 7: Run tests and iterate — 2026-09-02T20:01:00.000Z

All 8 parallel rounds are green: **121/121 passing in every round**.

## Summary

**Iterations run:** 2 (initial sweep → 1 fix batch → confirming sweep).

**Iteration 1 result:** 8/8 rounds at 118/121, with the *same* 3 tests failing deterministically in all 8 rounds (no flakiness anywhere in the suite; the sweep was otherwise stable).

All three failures shared one root cause: a test-local world builder walked the shipment only as far as custody `PACKAGED` while leaving `compliance_state` at `MANIFEST_DRAFT`, then invoked custody release. PRD §3.5 states: *"Its `compliance_state` must be `MANIFEST_CLOSED` — this is the one cross-dimension guard in the custody machine, and violating it yields `ERR_INVALID_COMPLIANCE_STATE`."* The implementation correctly returned `ERR_INVALID_COMPLIANCE_STATE`/409, so this was a STEP-2 test-setup bug (precondition inconsistent with PRD), not an implementation defect. The PRD-required guard was left untouched.

**Tests deleted:** none. Every failing test passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); the defect was in setup, not in the asserted rule.

**Fixes applied to `test_helpers/`:** none — the shared builders (`advance_intake`, `build_world`, stage ordering) were already PRD-faithful; both offending builders were file-local helpers in `test_suite/`.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/test_suite/test_06_boundary_precision.py` — helper `_lfp_priced_without_nickel_or_cobalt_quotes`: `stop_after` changed `"package"` → `"manifest_closed"` so the shipment satisfies the PRD §3.5 release precondition. Fixes `test_release_succeeds_with_no_quote_for_the_zero_recovery_metals` and `test_zero_lines_contribute_nothing_to_the_gross_or_the_waterfall`. Expected pricing figures unchanged (the added manifest steps do not move `received_at`, which is the provisional price basis date).
- `/home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/test_suite/test_02_triage_scoring_and_fork.py` — `test_only_the_material_recovery_branch_is_chargeable_into_a_lot` now builds its world with `_fork_world(api, stop_after="manifest_closed")` for the same reason (triage remains legal at custody `PACKAGED` per PRD §3.4, so the scenario's semantics are preserved).

**Fixes applied to `implementation/`:** none required. No assertion was weakened, no skip/xfail added, no PRD-required check removed.

**Orchestrator independent verification (per standing note that a Step 7 subagent can claim a clean sweep without leaving artifacts):** all 8 `results.{1..8}.json` exist on disk (~35.8 KB each, written 19:55), parse as JSON, and each reports `passed=121 total=121 failed=0`. `sweep.log` tail confirms the runner's own line `Results: 121/121 passed, 0 failed, 0 errors, 0 skipped`, `Duration: 223.9s`, and normal port-registry release — no `Terminated`, so the setsid wrapper held and no round was reaped. Claim confirmed.

## Step 8: Finalize PRD — 2026-09-02T20:10:00.000Z

Orchestrator note: Step 8's skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) did **not** apply — Step 7 made 2 `test_suite/` fixes across 3 tests — so the subagent was spawned. It then determined independently that no in-scope PRD edit was warranted.

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_2419_battery_recycling_second_life_recovery/workspace/PRD_FINALIZED.md` is a **byte-identical copy** of `PRD.md` (md5 `243f8bf933af4d33d33e3c3e65b0af3a`, 420 lines both, 0.0% delta). **Zero edits** — nothing in `<step_7_diff>` traces to a PRD silence or a PRD/impl mismatch.

## Why no edits were warranted

The Step 7 diff contains no `implementation/` fixes, no `test_helpers/` fixes and no test deletions. All three failures had one root cause — a test-local builder invoking custody release from custody `PACKAGED` with `compliance_state` still `MANIFEST_DRAFT` — and I confirmed against the implementation that the PRD already pins that behavior verbatim.

Per-item analysis (all three items share one subject, so one enumeration covers them):

- **Subject:** the custody-release preconditions and everything the two fixed builders newly walk through (manifest submit → close → release) plus the assertions those tests make downstream (provisional zero-lines / waterfall; triage-at-`PACKAGED` then charge).
- **Impl paths enumerated and read:**
  - `implementation/routes_intake.py:196-210` (`release_intake`) — checks in the exact PRD §3.5 order: `custody_state != PACKAGED` → `ERR_INVALID_CUSTODY_STATE`; `compliance_state != MANIFEST_CLOSED` → `ERR_INVALID_COMPLIANCE_STATE`; `credit_hold` → `ERR_SUPPLIER_CREDIT_HOLD`; then the settlement cut (which is where `ERR_INDEX_PRICE_UNAVAILABLE` can fire). Matches PRD §3.5 and §2.7 tier 8 < tier 13 as written. The failing tests hit exactly the second check, which PRD states word-for-word.
  - `implementation/routes_intake.py:218-265` (`submit_manifest`) and the close path — the added builder stages exercise only the success branches (submit legal at `DISCHARGED`/`PACKAGED` from `MANIFEST_DRAFT`; close requires `SUBMITTED` + `PACKAGED` + different actor), all of which PRD §3.3 already determines.
  - `implementation/routes_intake.py:426-442` (triage precondition) — guards only `module.status == PENDING_TRIAGE` and `custody_state in (PACKAGED, RELEASED)`, with no compliance-dimension guard, exactly as PRD §3.4 says. So `_fork_world(stop_after="manifest_closed")` triaging at custody `PACKAGED` / compliance `MANIFEST_CLOSED` is PRD-legal and semantics are preserved.
  - `implementation/calc.py:187-235` (`price_lines`, `provisional_contained`, `provisional_factors`) and `calc.py:249-265` (`waterfall`) — I re-derived every asserted figure in the two repaired `test_06` tests from PRD prose alone: LFP net 200 kg → NI `contained_kg` 10.000/CO 6.000 with `line_cents` 0 and no lookup (§3.5 zero-line rule), LI 13200, CU 3672, gross 16872, 12% fee 2025, pre-surcharge 14847, hazmat min(3700, 742)=742, net 14105. Also re-derived the `test_02` triage scores (85.40/A, 72.40/B, 48.80/D) and the 100.000 kg charge. All uniquely determined by PRD §3.4/§3.5/§3.7 — nothing needed pinning.
  - `test_helpers/fixtures.py:102-122, 503-559` (`INTAKE_STAGES`, `advance_intake`) — stage ordering is PRD-faithful; `received_at` is stamped once at booking (`routes_intake.py` create path) and the added manifest stages do not move it, so the provisional `price_basis_date` assertions are unaffected, as PRD §3.2/§3.5 already state.
- **Wording adjustment:** none — no candidate edit survived, since every behavior the repaired tests exercise is already stated in PRD.md.

Adjacent PRD silences I deliberately did **not** patch, because no Step 7 fix exercised them (out of HARD SCOPE, and patching would risk a new mismatch): `unit_price_cents_per_kg` being `null` rather than 0 on a zero-recovery line (`calc.py:199`), and the `ERR_INVALID_CUSTODY_STATE` code the impl returns for a manifest submission from `MANIFEST_DRAFT` with a wrong custody state (`routes_intake.py:231`). Both are pre-existing, unexercised by the three failures.

## Step 9: Complete PRD — 2026-09-02T20:20:00.000Z

Done. `PRD_COMPLETED.md` written.

## Source vs. output
- `PRD_FINALIZED.md`: 420 lines, 95,714 chars
- `PRD_COMPLETED.md`: 420 lines, 98,876 chars → **+3,162 chars**, 20 paragraphs touched, zero new sections/paragraphs (all inline)

## Counts
- **Ambiguity pins: 19**
- **Mismatch revisions: 4**

## Both flagged silences confirmed and pinned
- `calc.py:199` — in the zero-recovery branch of `price_lines`, the line dict carries `"unit_price_cents_per_kg": None` (with `line_cents: 0`). Confirmed, pinned.
- `routes_intake.py:231` — inside the `compliance == "MANIFEST_DRAFT"` branch, a custody state outside `("DISCHARGED","PACKAGED")` raises `ERR_INVALID_CUSTODY_STATE` (not `ERR_INVALID_COMPLIANCE_STATE`). Confirmed, pinned.

## Every change
- §2.3 — insert — ambiguity — filter query params are exact-equality matched and not enum-validated, so an undeclared value yields an empty page, not 400 — `core.py:520`
- §2.3 — insert — ambiguity — default `created_at` ascending ties (routine, since the clock is logical) break by insertion sequence — `core.py:158`
- §2.3 — insert — ambiguity — index-quote list ties break by `created_at` desc then insertion sequence desc — `routes_config.py:215`
- §2.5 — revise — ambiguity — clock may move backwards; response body carries only `current_utc` — `routes_config.py:50`
- §2.7 tier 3 — insert — ambiguity — both actor-identity rules resolve the addressed row first, so a tier-5 404 precedes `ERR_NOT_OWNER`/`ERR_SEGREGATION_OF_DUTIES` — `routes_intake.py:292`, `routes_settlement.py:80`
- §3.2 — insert — ambiguity — `soc_pct` is a required number with no range constraint; a null `identified_chemistry` also yields `ERR_INVALID_CUSTODY_STATE` — `routes_intake.py:167,171`
- §3.2 — revise — ambiguity — `horizon_days` is a required integer ≥ 1 — `routes_config.py:104`
- §3.3 — revise — ambiguity — first submission from `MANIFEST_DRAFT` with wrong custody → `ERR_INVALID_CUSTODY_STATE`; compliance dimension read first — `routes_intake.py:229-231`
- §3.3 — insert — ambiguity — manifest close with custody ≠ `PACKAGED` → `ERR_INVALID_CUSTODY_STATE`, checked after manifest status — `routes_intake.py:298`
- §3.3 — insert — ambiguity — resubmission custody/`hold_reason` guard → `ERR_INVALID_CUSTODY_STATE` — `routes_intake.py:238`
- §3.4 — insert — ambiguity — `scoring_variant` and `override_disposition` are echoed on the decision row — `routes_intake.py:450`
- §3.5 — revise — ambiguity — zero line reports `unit_price_cents_per_kg` as null, not 0 — `calc.py:199`
- §3.6 — revise — mismatch — `ERR_CAMPAIGN_FAMILY_MISMATCH` is evaluated last, after all three geometric checks (§2.7 tier 12), not first — `routes_recovery.py:117`
- §3.6 — revise — mismatch — lot opening is not gated on campaign `status` at all — `routes_recovery.py:194`
- §3.7 — insert — ambiguity — repeated identifiers in `module_ids` are collapsed before any check — `core.py:490`
- §3.7 — revise — mismatch — the `ERR_LOT_CHARGE_EXCEEDS_PLAN` ceiling precedes `ERR_INTAKE_NOT_RELEASED`/`ERR_MODULE_CHEMISTRY_MISMATCH` (tier 11 before 12), reversing the prose order — `routes_recovery.py:262`
- §3.7 — insert — ambiguity — `residue_mass_kg` is required and must be ≥ 0 — `routes_recovery.py:350`
- §3.7 — insert — ambiguity — voiding a lot in any other status → `ERR_LOT_NOT_OPEN` — `routes_recovery.py:435`
- §3.8 — revise — ambiguity — `ERR_PASSPORT_ALREADY_ISSUED` precedes the content floor; issuance is not gated on lot `status`, so a non-finalized lot (null `recycled_content_pct`) → `ERR_RECYCLED_CONTENT_BELOW_MINIMUM`; `metal_content` is in assay-ledger order — `routes_recovery.py:570-585`
- §3.8 — insert — ambiguity — suspending a non-`ACTIVE` allotment → `ERR_PERMIT_NOT_ACTIVE` — `routes_config.py:292`
- §3.9 — revise — mismatch — `ERR_DISPUTE_ROUNDS_EXHAUSTED` is checked before the variance test (tier 8 before 11) — `routes_settlement.py:87`
- §3.9 — revise — ambiguity — a `PROVISIONAL` variant and a null `max_variance_pp` both report `ERR_VARIANCE_WITHIN_TOLERANCE` — `routes_settlement.py:90-95`
- §3.9 — revise — ambiguity — umpire metal with no assay line on the contributing lot → `ERR_INVALID_REQUEST`, checked after the state gate; `umpire_contained_kg` ≥ 0 — `routes_settlement.py:114,121`

## Verified-aligned, left untouched
All 63 endpoint paths/roles/status codes match §4 exactly; the seven-step waterfall, triage scoring/grade bands/override matrix, quality-deduction components and caps, mass-balance and apportionment (remainder to latest `created_at`), permit daily UTC bucketing and lazy expiry, all cascades and version propagation, and every §5 error code/HTTP pairing already matched `core.ERROR_STATUS` with no drift. A few impl fallbacks (`provisional_factors` defaulting to `declared_chemistry`, zero-charged-mass balance) are unreachable given upstream gates, so I did not document them as behavior.

**Orchestrator verification:** `PRD.md` and `PRD_FINALIZED.md` are both 420 lines / 95,714 chars (byte-identical, as Step 8 reported); `PRD_COMPLETED.md` is 420 lines / 98,876 chars (+3,162), retains all 28 headings, and ends at the final error-table row — inline edits only, no truncation, no new sections.

---

## Pipeline complete — 2026-09-02T20:20:30.000Z

All nine steps finished. Final state: 15 entities / 63 endpoints / 62 error codes; 121 tests (58 queue A from 27 difficulty instances, 63 queue B from 63 non-stub corner instances), **121/121 passing in all 8 parallel sweep rounds**, results.{1..8}.json retained in `workspace/implementation/`. Deliverables: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/`, `test_suite/`, `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}`. Zero test deletions and zero implementation fixes were needed across the whole run.
