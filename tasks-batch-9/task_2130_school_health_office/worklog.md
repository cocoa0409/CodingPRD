# Worklog — task_2130_school_health_office

## Step 1: Create task directory — 2026-08-22T02:11:55.304Z

Created `tasks/task_2130_school_health_office/` and `tasks/task_2130_school_health_office/workspace/`. Index 2130 chosen as max existing (2129) + 1.

## Step 3: Copy shared files — 2026-08-22T02:11:55.304Z

Copied `./INSTRUCTION.md` → `tasks/task_2130_school_health_office/workspace/INSTRUCTION.md` (performed early alongside Step 1; no dependency on Step 2).

## Step 2a: Generate SCAFFOLD.yaml — 2026-08-22T03:22:57.793Z

(First attempt at a combined Step 2 subagent died with "response exceeded the 64000 output token maximum" and wrote zero files; Step 2 was split into 2a = SCAFFOLD.yaml and 2b = the two design indices, each writing incrementally.)

SCAFFOLD.yaml generated at `/home/ubuntu/github/CodingPRD/tasks/task_2130_school_health_office/SCAFFOLD.yaml`.

**Counts**
- Entities: 11 (School, Nurse, CoverageAssignment, Student, ActionPlan, MedicationAuthorization, MedicationStockLot, HealthVisit, AdministrationRecord, Screening, DisclosureRequest)
- State machines: 7 | Concurrency rules (OCC): 3
- Calculations: 13 | Validations: 49 (single global priority ladder 1-49)
- Endpoints: 56 | Errors: 49 | Roles: 6
- Total lines: 2364

**Profile** — archetype compliance_audit + quota_allocation; layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / ops_run_checkpoint; topology **flat**; role_model **segregation_of_duties**; self-referential FK (`ActionPlan.supersedes_action_plan_id`); api_prefix `/health-office`; logical clock default `2026-08-01T00:00:00Z`.

**Beyond-expert difficulty coverage (§0.5, >=2 instances each, all differentiated)**
- R1 dual-variant: `school_nurse_coverage_ratio` (CONTRACTED vs DELIVERED, School staffing) / `student_risk_scoring` (INTAKE vs OBSERVED, Student clinical) — different entity domains.
- R2 combinatorial: mode (a) `visit_triage_score` nested min/max on 4 inputs; mode (b) `school_days_of_supply` pinned round-per-lot-then-sum-then-round; mode (c) `stock_protocol_requirement` base->surge(base)->total, explicitly non-re-tiered.
- R3 non-linear SMs: MedicationAuthorization (two independent dimensions, both cyclic), HealthVisit (4-way disposition fork + CLOSED->REOPENED cycle), ActionPlan and Screening cycles.
- R4 cascades: plan-approve chain (SUPERSEDED->suspend orders->void prepared->lot restock/posture, depth 4) and lot-quarantine chain (void->release->days-of-supply->stock_protocol_status->coverage_posture, depth 4) — different triggers.
- R5 priority conflicts, 4 distinct category pairs: state x safety (9 vs 23), temporal x constraint (32 vs 35), safety x constraint (18 vs 34), temporal x fiscal (33 vs 47).
- R6 boundaries: PRN `elapsed >= interval` and daily cap `<`; empty-set (zero delivered minutes -> null ratio -> UNCOVERED); READY at exactly 30.00 days; triage `>= 85`.
- R7 cross-entity pairs: AdministrationRecord->MedicationAuthorization, HealthVisit->School, MedicationAuthorization->ActionPlan, HealthVisit->CoverageAssignment, DisclosureRequest->Student.
- R8 overlap, different interval semantics: pairwise half-open + 20-min travel buffer on **Nurse** (priority 33) vs aggregate cot capacity with closed intervals on **School** (priority 34).
- R9 conserved quantities: `MedicationStockLot.received_total` (physical units, PREPARE/ADMINISTER/VOID compensation) and `Nurse.weekly_contracted_minutes` (staffing time, CREATE/END compensation).

**Verification**
- `yaml.safe_load` parses; top-level keys: api_prefix, calculations, complexity_profile, concurrency_rules, domain_name, endpoints, entities, errors, response_envelope, roles, scenario, state_machines, validations. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` present.
- `scaffold_lint.py` (run with empty §1.8/§1.9 stubs in scratchpad, not written to the task dir): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (56 endpoints, 11 entities).
- Scans clean for forbidden concurrency vocabulary, fuzzy ranking adjectives, and `id`-based business decisions (tie-breaks use `created_at ASC`).
- Note for downstream: PyYAML rejects unquoted `foo?` in flow sequences, so optional `input:` items are quoted strings.

## Step 4: Generate PRD — 2026-08-22T03:33:24.337Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2130_school_health_office/workspace/PRD.md` — **400 lines**, built across 8 incremental appends (max ~31 lines of markdown per call; no single call approached the token ceiling).

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity/Versioning/Timestamps · 2.5 Logical Clock & Daily Checkpoint · 2.6 OCC on Parent Records · 2.7 The Global Validation Ladder · 2.8 Precision/Rounding/Boundaries · 2.9 Credentialled Practice & Segregation of Duties · 2.10 Conserved Quantities · 2.11 Cascade Discipline
- §3 Business Logic (9 subsections): 3.1 Buildings/Nurses/Coverage · 3.2 Student Profile & Risk · 3.3 Action Plans & Supersede Cascade · 3.4 Medication Orders (two dimensions) · 3.5 Stock Lots/Selection/Readiness · 3.6 Office Encounter · 3.7 Giving & Undoing a Dose · 3.8 Screenings · 3.9 Record Disclosure
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Coverage audit (verbatim results, after gap closure)**
```
entity fields:      129 unique required, 129 present, 0 missing
endpoint inputs:     81 required (incl. limit/offset/expected_*_version/
                     to_iso8601/action/decision/note/alert_flag/
                     initial_quantity/redaction_override), 81 present, 0 missing
entity names:        11 required, 11 present, 0 missing
state values:        35 required, 35 present, 0 missing
state machines:       7 covered (ActionPlan, MedicationAuthorization, HealthVisit,
                     AdministrationRecord, MedicationStockLot, Screening, DisclosureRequest)
calculations:        13 required, 13 fully expressed, 0 missing
validations:         49 required, 49 present with an EXPLICIT ladder position in prose,
                     0 missing (all 4 declared priority conflicts named)
concurrency rules:    3 required, 3 expressed (write_endpoint + occ_field + error_id + 412)
errors:              49 required, 49 in §5 table and 49 referenced in §2/§3 prose, 0 missing
endpoints:           56 required, 56 in §4 table, 0 missing
roles:                6 required, 6 named with identity semantics translated, 0 missing
§3 path purity:     311 backtick tokens scanned; 0 leading-slash, 0 bare-method,
                     0 method+path — PASS
§2.2 verbatim:      byte-for-byte identical to section-2.2-response-structure.md — PASS
```

**Gaps found and closed during the audit (2):** `alert_flags` appeared only as prose "alert flags" (now backticked in §3.2); `CoverageAssignment` entity name never appeared literally (now named in §3.1). Re-audit after fixes: **no gaps.**

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read, and no sibling `task_*/` directory was accessed.

## Step 6: Generate implementation — 2026-08-22T03:58:55.749Z

(Launched early, concurrently with Step 2b, since it depends only on SCAFFOLD.yaml + PRD.md + INSTRUCTION.md. Explicitly forbidden from reading `test_helpers/`, `test_suite/`, and both design indices.)

Implementation complete and verified.

**Files** (`workspace/implementation/`, 3366 LOC total incl. `start.sh`/`requirements.txt`)

| File | LOC | Owns |
|---|---|---|
| `calc.py` | 546 | all 13 calculations: dual-variant coverage ratio (CONTRACTED/DELIVERED), dual-variant risk scoring, triage score w/ nested clamps, pinned double-rounded days-of-supply, stock requirement (base->surge->total, never re-tiered), protocol status, posture, PRN dose gate, FEFO lot selection, screening thresholds, redaction+package |
| `routes_records.py` | 327 | screenings + disclosure requests |
| `routes_meds.py` | 298 | medication orders (2 independent dimensions) + stock lots/inventory actions |
| `routes_students.py` | 293 | students + action plans (revision cycle, supersede) |
| `routes_admin.py` | 278 | administration records: both reservations, outcomes, void |
| `routes_visits.py` | 238 | encounters: create/assess/4 dispositions/close/reopen |
| `serializers.py` | 238 | resource shapes + always-fresh derived fields |
| `routes_provision.py` | 232 | schools, nurses, coverage blocks (interval rule 1 + minute conservation) |
| `store.py` `cascades.py` `routes_ops.py` `validators.py` `auth.py` `envelope.py` `errors.py` `app.py` | 182/144/141/127/91/77/69/76 | in-memory dicts + logical clock; 4-hop supersede & quarantine cascades + void compensation; clock + daily checkpoint; ladder 5/6; ladder 1-4; envelope + pagination; 49-error catalog; Flask wiring |

**Key decisions** (PRD-literal where scaffold disagreed)
- Clock-dependent derived fields (coverage status, `dispensable`, all School figures, `pending_administration_count`, per-lot days of supply, alert flags/tier/plan pointer) are evaluated on read, so they are never stale; `observed_risk_score` is stored and refreshed only at the six declared triggers (right-exclusive 90-day window, literal).
- Every endpoint runs its checks in ascending global ladder position; the 4 declared collisions verified live (visit-state 9 > consent 23; PRN 32 > cap 35; posture 18 > cot 34; overlap 33 > hours 47).
- `_seq` insertion counter is the stable tie-break after `created_at` (default ordering + final FEFO tie-break); lot `id` never consulted.
- Lot selection: pool with the units filter wins first; if empty, a pool without it distinguishes `ERR_NO_ELIGIBLE_LOT` from `ERR_INSUFFICIENT_STOCK`.
- Undeclared preconditions mapped to the nearest declared error: cross-parent mismatches -> 404; `REFERRED_EXTERNAL` complaint gate -> `ERR_VISIT_INVALID_STATE`; non-RN/wrong-role `VERIFY`/`SUSPEND` -> `ERR_ROLE_NOT_PERMITTED`.
- `touch()` bumps `version`/`updated_at` once per record per request, so each cascade hop advances its own records exactly once.

**Storage/boot**: pure Python dicts, zero seeding (`total_count` is 0 on every restart), no filesystem writes; `start.sh` reads `$PORT`, binds 0.0.0.0, guards `pip install` on a flask import, and `exec`s the server in the foreground.

**Boot check**: launched fresh on port 18455 — well-formed envelopes (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), 401 without headers, school create returned `UNCOVERED`/`DEPLETED`/`version 1` as the PRD requires for an empty building. Five end-to-end smoke suites (~120 assertions) exercised conservation invariants (`received_total` = 4 buckets after prepare->administer->void; nurse minutes restored on block end), both 4-hop cascades, OCC on all three parents, checkpoint expiries, segregation of duties, and every error band.

## Step 2b: Generate design indices — 2026-08-22T04:02:00.000Z

Both design files are complete and verified. SCAFFOLD.yaml was not modified.

**§1.8 — SCAFFOLD_DIFFICULTY_DESIGN.yaml (1470 lines, top-level key `scaffold_difficulty_design`)**
18 instances, 2 per rule, all non-stub with pre-computed literal asserts:
dual_variant_calc 2 · combinatorial_formula 2 (modes (a) nested-clamp triage=77 vs naive 87, (b) round-per-lot-then-sum 6.66 vs 6.67) · non_linear_state_machine 2 · transitive_cascade 2 (two depth-4 chains, different triggers) · priority_pair_validation_conflict 2 (conflicts A and D) · boundary_precision_check 2 (triage exactly 85; empty lot pool) · cross_entity_state_dependency 2 · resource_temporal_overlap 2 (Nurse half-open + 20-min buffer; School closed-interval aggregate) · compensating_invariant 2 (lot units; nurse minutes).

**§1.9 — SCAFFOLD_CORNER_DESIGN.yaml (4576 lines, top-level key `scaffold_corner_design`)**
89 instances / 75 non-stub + 14 `excluded_because` stubs:
entities 10 (0 stubs) · state_machines 13 (2) · calculations 10 (2) · validations 7 (0) · endpoints 5 (0) · rbac 9 (0) · cross_cutting_complexity_layers 6 (2) · consistency_model 2 (1) · errors 27 (7).

**Totals:** 107 instances, 93 non-stub, 14 stubs; 861 API calls across both files.

**Verification (custom script, all passing):** every `grounds` ref resolves verbatim (error_id / validation priority / calculation name / concurrency rule_id / entity.field / state-machine state / endpoint / role); zero unbound `${var}` in any payload, path, `as_user_id`, or assert; every capture bound before use; every stub's `difficulty_instance` exists in §1.8 and carries no `test_recipe`; all 107 names unique across the union; no empty setup/trigger/assert. 48 of 49 error codes are positively asserted or stubbed — the 49th, `ERR_GUARDIAN_CONSENT_MISSING`, is provably unreachable in this scaffold (a plan at `PENDING_PROVIDER` always has `guardian_consent_at` set, since `REQUEST_REVISION` clears it only while sending the plan back to `DRAFT`), so it is covered honestly by the `guardian_consent_missing_is_masked_by_plan_state_check` priority-ordering instance, which asserts the priority-7 row wins with `ERR_PLAN_INVALID_STATE`.

Clock discipline: default `2026-08-01T00:00:00Z` is a Saturday and `weekday` is MON–FRI only, so every recipe needing the on-coverage check sets the clock to `2026-08-03T09:00:00Z` (Monday, minute 540); recipes reading the 90-day OBSERVED window advance the clock before the read because the window is right-exclusive.

**Linter verdict (pasted verbatim):**
```
Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  861

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 5: Generate unit tests — 2026-08-22T04:38:37.973Z

Test infrastructure and suite are complete.

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2130_school_health_office/`)

`test_helpers/` (1,590 lines): `types.py` 378, `api_client.py` 190, `api_errors.py` 112, `assertions.py` 147, `factories.py` 157, `constants.py` 67, `test_users.py` 54, `fixtures.py` 443, `__init__.py` 42.

`test_suite/` (3,878 lines): `conftest.py` 51, `test_01_provisioning.py` 426, `test_02_students.py` 325, `test_03_action_plans.py` 282, `test_04_medication_orders.py` 217, `test_05_stock_lots.py` 485, `test_06_encounter_triage.py` 258, `test_07_encounter_gates.py` 432, `test_08_dose_preparation.py` 565, `test_09_dose_outcomes.py` 188, `test_10_screenings.py` 194, `test_11_records_release.py` 238, `test_12_access_control.py` 217.

**Counts** — 111 tests, all collected cleanly by pytest.
- Queue A: 18/18 difficulty instances translated, exactly 2 tests each = 36 tests. 0 skipped.
- Queue B: 75/75 non-stub corner instances translated, 1 test each = 75 tests. 0 skipped. The 14 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were not translated.

**Audit results** (scripted): every docstring carries exactly one `Design:` line; all 111 tags resolve to real instance names; no tag points at a stub; no dual/untagged tests; every quoted PRD citation (>=4 words) survives a literal normalized-whitespace match against `workspace/PRD.md`; no `skip`/`skipif`/`xfail`; no scaffold references in emitted code.

**Constants drift found (PRD wins, re-derived)**
1. `boundary_precision_check/triage_exactly_85_admits_ems_transport_83_does_not` — the design computes visit B (URGENT + INJURY, CRITICAL anaphylaxis student, LIMITED posture) as `40 + 10 + 25 + 8 = 83`, applying the 15-point anaphylaxis bonus. PRD §3.6 grants that bonus only when `complaint_code` is `ILLNESS` or `MEDICATION`, so the uplift is `min(25, 20) = 20` and the score is **78**. Test asserts 78; the assertion under test (refusal with `ERR_EMS_DISPOSITION_NOT_JUSTIFIED`) is unaffected.

**Assertions deliberately not emitted** (PRD-silence, within otherwise-translated instances)
- `Corner/entities/school_creation_seeds_derived_fields_and_default_protocol_flag`: dropped the `base_required_units == 0` / `surge_units == 0` field assertions — PRD names those two only inside the stock-requirement formula, never as building fields a reader must serialize (`required_stock_units`, `eligible_stock_student_count` are named outside the formula and are asserted).
- `Corner/endpoints/daily_checkpoint_returns_epoch_and_recomputed_school_ids`: asserted `epoch` presence rather than integer type — PRD says the sweep "reports `epoch`" but never pins its type.
- Null-valued fields are asserted via `data.get(field) is None`, so an implementer who omits an unset optional field rather than serializing `null` is not failed.

## Step 7: Run tests and iterate — 2026-08-22T04:45:00.000Z

All 8 parallel rounds pass 111/111 with zero union failures. Test count is intact at 111, no skips/xfails introduced, and storage remains in-memory with no seeding.

**Orchestrator independent verification:** re-read all 8 `results.{1..8}.json` — every round `passed=111 total=111 failed=0`; grep of `test_suite/` finds no `pytest.mark.skip`/`xfail`; test-function count is 111.

## Summary

**Iterations run:** 2 (two full 8-round parallel stability sweeps).

- **Sweep 1:** 107/111 in all 8 rounds. Union of failures = 4 tests, identical in every round — no flakiness anywhere in the suite.
- **Sweep 2 (verification):** 111/111 in all 8 rounds, union failures = 0.

**Tests deleted:** none. All 4 failing tests passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); no PRD-silence or collapse pattern applied.

**Fixes applied to `test_helpers/`:** none. The failures did not trace to fixtures, factories, or role-header builders.

**Fixes applied to `test_suite/`:**
- `test_suite/test_01_provisioning.py` → `test_marking_a_nurse_inactive_recomputes_the_delivered_ratio_and_posture`: replaced the hardcoded `assert patched["version"] == 2` with a read of the nurse immediately before the PATCH and `assert patched["version"] == before_nurse["version"] + 1`. The literal `2` contradicted PRD §2.4 ("each touched record's own `version` advances… cascade-driven changes written by the server on the operator's behalf") combined with PRD §3.1 (coverage-block creation moves the nurse's `committed`/`uncommitted_weekly_minutes` and refreshes `assigned_school_count`) — the create-coverage step is itself a PRD-required nurse mutation, so the nurse is already at version 2 before the amendment and the PATCH correctly yields 3. I verified against the running server that the implementation bumps exactly once per step (create=1, coverage=2, patch=3), so this was a test-side arithmetic error, not an implementation double-bump. The new assertion is strictly more faithful to the cited sentence ("either amendment increments the nurse's `version`") and remains an exact equality — no weakening.

**Fixes applied to `implementation/`:**
- `workspace/implementation/calc.py` → `coverage_ratio()`: the ratio was computed in two steps as `fte = weekly / 2100` then `enrolled / fte`. The intermediate `fte` is quantized to Decimal's 28-significant-digit context, so the second division inherited the truncation and produced `4.374999999999999999999999999` where the exact value is `4.375` — rounding half up to **4.37** instead of **4.38**. Rewritten as the single unrounded expression `round2(Decimal(enrolled) * Decimal(FULL_TIME_WEEKLY_MINUTES) / weekly)`, which is what PRD §3.1 pins: "dividing the unrounded minutes and rounding exactly once at the end."

  This one bug accounted for **all 4 union failures** — it surfaced in `test_01_provisioning` (undelegated-aide delivered minutes), `test_06_encounter_triage` (risk-uplift clamp), and `test_07_encounter_gates` (posture lift), each of which reads a building ratio as a precondition. Before applying it I confirmed by replaying every ratio asserted anywhere in `test_suite/` that only the `4.375` half-up boundary case changes value; `5.53`, `11.05`, `13.13` and `14.58` are identical under both formulations, so the fix could not mask a regression elsewhere.

**Notes for the later PRD-alignment step:**
- I audited the sibling rounding path (`lot_days_of_supply` / `school_days_of_supply`) against PRD §2.8's contrasting rule — "rounds each lot's own quotient first, sums the already-rounded terms, and then rounds the sum a second time." The implementation already matches, and none of the five `AVG_DAILY_UNITS` divisors can produce a `.xx5` tie, so no half-up boundary is reachable there.
- No implementation check was removed or weakened, no endpoint/field/side-effect was added, and no assertion was downgraded to an HTTP-status check.

## Step 8: Finalize PRD — 2026-08-22T04:52:00.000Z

PRD_FINALIZED.md written.

**Line counts:** PRD.md 400 → PRD_FINALIZED.md 400 (0.0% line delta; 2 lines revised, +493 chars = +0.52% by size).

**Changes**
- §2.4 Resource Identity, Versioning and Timestamps — revise — appended a per-operation cap: several hops of one operation touching the same record advance its `version` at most once for the whole operation (not once per hop) and stamp `updated_at` once — `implementation/store.py:165-176` (`touch()` dedupes by record identity in a per-request `flask.g` set).
- §3.1 The nurse-to-student coverage ratio — revise — pinned the quotient's algebraic form (`enrolled × 2100 ÷ minutes` as one exact expression, no intermediate FTE materialised or truncated) and the half-cent tie example 4.375 → 4.38 — `implementation/calc.py:274-282`.

**Pre-edit search log**

Edit 1 (§2.4)
- (a) Subject: how many times one record's `version`/`updated_at` advance within a single request/cascade.
- (b) Enumerated: `grep -rn '"version"' implementation/*.py` → only writers are `store.py:146` (init to 1) and `store.py:176` (increment inside `touch`); all three `expected_*_version` reads (`routes_admin.py:72`, `routes_students.py:153`, `routes_meds.py:269`) are comparisons only. Read `store.py:153-176` (`touched_set`/`touch`), all ~50 `touch(` callsites by file (`cascades.py` 8, `routes_students.py` 8, `routes_records.py` 7, `routes_visits.py`/`routes_meds.py` 6, `routes_admin.py`/`routes_ops.py` 5, `routes_provision.py` 4). Checked the multi-touch paths specifically: `cascades.void_record` → `move_units` + `refresh_lot_state` (two touches of one lot), `supersede_cascade` and `quarantine_cascade` (plan/lot + orders + records), `routes_provision.py:171-173` and `:227-231` (nurse counters vs. block), and the daily checkpoint in `routes_ops.py`. Also confirmed School derived fields are computed live at serialize time (`serializers.py:14`, `calc.py:351`) and the school record is never `touch`ed.
- (c) Wording adjusted from "advances by exactly one" to "advances **at most once** for the whole operation" so the sentence stays true for records that are never touched at all (schools, whose derived figures recompute on read) while still forbidding the per-hop double-bump; kept the existing "each touched record's own `version` advances" sentence intact so the >=1 half still comes from PRD prose.

Edit 2 (§3.1)
- (a) Subject: the students-per-nurse-FTE quotient and its rounding point.
- (b) Enumerated: `grep -rn "coverage_ratio\|per_nurse_fte" implementation/*.py` → `calc.coverage_ratio` is the sole definition with exactly two callsites (`calc.py:363-364`, contracted and delivered) and no route-level duplicate. Read `calc.py:63-68` (`round2` = `quantize("0.01", ROUND_HALF_UP)`), `contracted_weekly_minutes`/`delivered_weekly_minutes` (`calc.py:253-271`) to confirm the ratio consumes the *unrounded* weighted sum while `delivered_weekly_minutes` is separately `round2`-ed for reporting (`calc.py:373`), and the sibling rounding paths `lot_days_of_supply`/`school_days_of_supply` (`calc.py:285-303`) which deliberately round-then-sum-then-round per §2.8.
- (c) Scoped the new sentence to "the quotient" inside the coverage-ratio paragraph only — no general claim about rounding — so §2.8's contrasting two-stage days-of-supply rule and the separate `round2` applied to reported `delivered_weekly_minutes` are untouched; §2.8's own one-line summary of the ratio was left verbatim.

No other `<step_7_diff>` item produced an edit: the `test_01_provisioning` version assertion was a test-side arithmetic error already determined by §2.4 + §3.1 (the only residual freedom, per-hop double-bumping, is what Edit 1 closes), and no `test_helpers/` or deletion items existed.

## Step 9: Complete PRD — 2026-08-22T04:59:11.621Z

Done. `PRD_COMPLETED.md` is written.

**Orchestrator verification:** `workspace/implementation/` was NOT modified by Step 9 (latest impl mtime 04:41, Step 9 ran 04:49–04:58), so the clean 8-round 111/111 sweep from Step 7 still holds.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 400 lines / 94,432 chars → `PRD_COMPLETED.md` 400 lines / 104,527 chars (**+10,095 chars**, 40 lines revised in place; no new sections, no new paragraphs).

**Counts:** 56 edits — **50 ambiguity-pins**, **6 mismatch-revisions**.

- 2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock, the one instant not from the logical clock; pagination meta omitted on object/error responses — envelope.py:16
- 2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_FIELD_VALUE`; list tie-break is insertion order; filter values are exact-match and not enum-checked — envelope.py:58, store.py:179
- 2.4 — revise — mismatch — read-time derived fields (school figures, student tier/flags/pointer, block `status`, `assigned_school_count`, `dispensable`, dose counters, `pending_administration_count`, `quantity_available`, `days_of_supply`) do **not** advance the holder's `version` — serializers.py:6, store.py:165
- 2.5 — insert — ambiguity — clock accepts any instant incl. backwards; `data` is `{current_utc, previous_utc}` only — routes_ops.py:14
- 2.5 — insert — ambiguity — `epoch` starts 0 / +1 per sweep; sweep order; arrays ordered by `created_at`; `voided_administration_ids` accumulation order; `school_id` narrows by *student's* building for plans/orders/disclosures but by own `school_id` for lots/screenings; `recomputed_school_ids` lists all in scope — routes_ops.py:28
- 2.7 — insert — ambiguity — a cross-parent reference miss is also `ERR_RESOURCE_NOT_FOUND` — routes_meds.py:36
- 2.1 — insert — ambiguity — ownership can't precede a missing row; existence answers instead — routes_students.py:63
- 3.1 — insert — ambiguity — bad `building_code` shape is position-6 `ERR_INVALID_FIELD_VALUE`, reached before the duplicate check — routes_provision.py:36
- 3.1 — insert — ambiguity — empty building: days-of-supply 0.00, ratios null; `eligible_stock_student_count`, `base_required_units`, `surge_units`, `contracted_weekly_minutes`, `delivered_weekly_minutes` are response fields — calc.py:366
- 3.1 — insert — ambiguity — nurse PATCH with neither field supplied still succeeds and still bumps `version` — routes_provision.py:94
- 3.1 — insert — ambiguity — `delivered_weekly_minutes` reported rounded to 2dp; the unrounded sum feeds the ratio — calc.py:373
- 3.1 — insert — ambiguity — block-end has no from-state check, no ordering constraint on `effective_to`, and returns minutes exactly once — routes_provision.py:223
- 3.2 — insert — ambiguity — `date_of_birth` accepts date or timestamp, echoes a full UTC timestamp — serializers.py:68
- 3.2 — insert — ambiguity — all amendment fields optional; `enrollment_status` may be set back to `ENROLLED`; version bumps regardless — routes_students.py:96
- 3.2 — insert — ambiguity — screening-declination fires only on the `ENROLLED` → non-`ENROLLED` edge — routes_students.py:115
- 3.2 — insert — ambiguity — `active_action_plan_id` tie broken by most recently created plan — calc.py:184
- 3.3 — insert — ambiguity — `supersedes_action_plan_id` need only exist (any student, condition, state) — routes_students.py:139
- 3.3 — insert — ambiguity — approval's position-17 enrolment check precedes the position-25 consent check — routes_students.py:251
- 3.3 — insert — ambiguity — plan `note`/`reason_code` stored but not returned — serializers.py:86
- 3.4 — insert — ambiguity — PRN interval absence = `ERR_MISSING_REQUIRED_FIELD`, presence on `SCHEDULED` = `ERR_INVALID_FIELD_VALUE`; bad validity window = `ERR_INVALID_FIELD_VALUE` — routes_meds.py:55
- 3.4 — insert — ambiguity — plan under another student = `ERR_RESOURCE_NOT_FOUND` at position 4 — routes_meds.py:36
- 3.4 — insert — ambiguity — redundant `GRANT`/`WITHDRAW` = `ERR_AUTHORIZATION_INVALID_STATE` at 8 — routes_meds.py:121
- 3.4 — revise — mismatch — `VERIFY` requires role `SchoolNurse` **and** `RN`; both refusals are `ERR_ROLE_NOT_PERMITTED` at position 2, before the order is looked up; non-`ACTIVE` linked plan = `ERR_PLAN_INVALID_STATE` at 7 — routes_meds.py:145
- 3.4 — revise — mismatch — `SUSPEND` restricted to `SchoolPhysician` via `ERR_ROLE_NOT_PERMITTED` at 2 — routes_meds.py:151
- 3.4 — insert — ambiguity — clinical-review `note` accepted and discarded — routes_meds.py:155
- 3.5 — insert — ambiguity — `units` required for `RECEIVE`/`DISCARD`, ignored by `QUARANTINE`/`RESTORE`; lot `reason_code` not returned — routes_meds.py:254
- 3.5 — insert — ambiguity — `RESTORE` yields `AVAILABLE` even at zero on hand — routes_meds.py:296
- 3.5 — insert — ambiguity — `RECEIVE`/`DISCARD` admitted from `AVAILABLE`, `QUARANTINED`, `DEPLETED` — routes_meds.py:265
- 3.5 — insert — ambiguity — a reservation emptying `quantity_on_hand` does not deplete the lot — routes_admin.py:39
- 3.5 — insert — ambiguity — lot-selection final tie-break is insertion order — calc.py:476
- 3.5 — revise — mismatch — selection filters on code, so `ERR_LOT_MEDICATION_MISMATCH` is in practice the order-to-encounter student mismatch — routes_admin.py:105
- 3.6 — revise — mismatch — student/building mismatch = `ERR_RESOURCE_NOT_FOUND` at 4, before the enrolment check — routes_visits.py:43
- 3.6 — insert — ambiguity — encounter `nurse_id` need not equal `X-User-ID` — routes_visits.py:60
- 3.6 — insert — ambiguity — omitted `assessment_note` leaves the stored note standing — routes_visits.py:117
- 3.6 — insert — ambiguity — `guardian_notified` optional/defaults false; ignored on `RETURN_TO_CLASS` and `REFERRED_EXTERNAL` — routes_visits.py:132
- 3.6 — revise — mismatch — `REFERRED_EXTERNAL` complaint mismatch = `ERR_VISIT_INVALID_STATE` at 9, ahead of all other disposition rules — routes_visits.py:137
- 3.6 — insert — ambiguity — reopen evaluates cot (34) → window (36) → round cap (45); `reason_code` not returned — routes_visits.py:216
- 3.7 — insert — ambiguity — acting `X-User-ID` must name an existing `Nurse` row on all three administration steps, else `ERR_RESOURCE_NOT_FOUND` at 4 — routes_admin.py:57
- 3.7 — insert — ambiguity — student mismatch checked at 42, after the dose gate and before lot selection — routes_admin.py:105
- 3.7 — insert — ambiguity — a witness on a non-controlled dose is recorded but never compared — routes_admin.py:116
- 3.7 — revise — mismatch — emergency stock: credential (20) precedes `ERR_STOCK_PROTOCOL_DISABLED` (30); witness/segregation never reached — routes_admin.py:156
- 3.7 — insert — ambiguity — outcome requires the witness supplied afresh and overwrites the stored one — routes_admin.py:229
- 3.7 — insert — ambiguity — void `reason_code` required; window measured from `prepared_at` in every source state; cascade voids write none — routes_admin.py:272, cascades.py:60
- 3.8 — insert — ambiguity — screening student/building mismatch = `ERR_RESOURCE_NOT_FOUND` at 4 — routes_records.py:34
- 3.8 — insert — ambiguity — record-result coverage check ignores weekday and minute-of-day — routes_records.py:98
- 3.8 — insert — ambiguity — conditional `scheduled_for` / `referral_outcome` = `ERR_MISSING_REQUIRED_FIELD` at 5, before the from-state check; `rescreen_due_at` and `referral_due_at` left standing — routes_records.py:130
- 3.9 — insert — ambiguity — non-tightening `redaction_override` accepted and silently ignored — routes_records.py:286
- 3.9 — insert — ambiguity — release recomputes the level but never loosens an override-set `PARTIAL`; privacy (29) precedes expiry (38) — routes_records.py:309
- 4 — revise — mismatch — clock and checkpoint return a report object, not a resource; unmatched path/method = `ERR_RESOURCE_NOT_FOUND` 404 — routes_ops.py:20, app.py:53
