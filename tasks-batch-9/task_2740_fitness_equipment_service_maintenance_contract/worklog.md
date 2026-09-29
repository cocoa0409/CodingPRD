# Worklog — task_2740_fitness_equipment_service_maintenance_contract

## Step 1: Create task directory — 2026-09-04T14:08:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract` and `workspace/` (pre-assigned path from the invocation; no index auto-allocation performed).

## Step 2: Generate Scaffold — 2026-09-04T15:53:00.000Z

All three scaffold artifacts for task 2740 are complete, parse cleanly, and the lint is green.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/SCAFFOLD.yaml` | 2655 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 934 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/SCAFFOLD_CORNER_DESIGN.yaml` | 2538 |

All three `yaml.safe_load` cleanly. `SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. The other two files each have exactly one top-level key.

## SCAFFOLD.yaml (§1.0–§1.7)
`domain_name: fleetcare-service-contracts`, `api_prefix: /fleetcare`; archetype "Ledger reconciliation" + "Compliance / audit"; layers dual-variant calculation, cascading side effects, optimistic concurrency, selector policy; flat topology, parallel state machines, `segregation_of_duties`, `immediate` consistency.

12 entities · 9 state machines · 2 concurrency rules (both on `expected_contract_version`) · 15 calculations · 63 ordered validations · 65 endpoints · 62 error codes · 6 roles.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
9 rule_ids × 2 = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
9 sections, **79 instances** — 61 with full `test_recipe`s, 18 `excluded_because` stubs: entities 11, state_machines 29, calculations 13, validations 8, endpoints 5, errors 1, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1.

## Lint
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(1174 calls scanned across 18 §1.8 + 61 §1.9 recipes.)

## Coverage-audit notes
- **Error catalogue: 62/62 triggerable.** 59 are triggered directly by §1.9 recipes; `ERR_CLUB_VISIT_CAPACITY`, `ERR_TECHNICIAN_WINDOW_CONFLICT` and `ERR_PART_SOURCE_UNAVAILABLE` are carried by §1.8 and cited from `excluded_because` stubs. Verified programmatically that every code string appears in at least one recipe body (comment block excluded from the scan).
- **All 18 stub citations resolve** to real §1.8 instance names; 3 §1.8 instances (`renewal_quote_pricing_stacks_age_parts_history_and_compliance`, `pm_compliance_empty_history_snapshots_exactly_100_pct_on_a_quote`, `new_part_sourcing…` — the last now cited) are not duplicated at corner level by design.
- **No name collisions** across the two design files.
- N/A sections recorded in a trailing comment block: entity immutability/parent-relationships (flat topology, `common_fields: true`), bubble-up and compound side effects, bulk endpoints, topological/decay/projection calculation rows, six unused layers, and the eventual/saga consistency variants.
- Two defects found and fixed during verification: eight `expected_*_version` literals violated lint rule (e) — each now reads a version captured from a preceding `GET /fleetcare/contracts/{id}` (the deliberate stale test uses `"${v_pre} - 1"`); and a capture of `equipment_health_score` off a `ServiceCall` response was re-pointed at `GET /fleetcare/equipment/{id}` → `health_score`.

## Step 3: Copy Shared Files — 2026-09-04T15:53:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2740_fitness_equipment_service_maintenance_contract/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T16:14:00.000Z

PRD complete and verified.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/workspace/PRD.md` — **516 lines, 119,966 bytes**, ending at a real section boundary (the last row of the §5 error table; no audit footer, no truncation).

The two withheld design YAMLs were never opened, and no other task directory was read.

## Section outline
- §1 Introduction (3 paragraphs: reconciliation, safety, obsolescence)
- §2 Global Specifications — 2.1 Roles/RBAC, 2.2 API Response Structure (verbatim block, all four sentinels intact), 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Logical Service Clock, 2.6 Peer Addressing & Left-to-Right Resolution, 2.7 Money/Minutes/Scores/Rounding, 2.8 Contract Version as OCC Token, 2.9 The Rejection Ladder, 2.10 Cascade Discipline & Derived Counters, 2.11 Three Standing Invariants
- §3 Business Logic — 3.1 Clubs/Models/Fleet, 3.2 Coverage Agreement, 3.3 Technician Pool & Routing, 3.4 Preventive Maintenance, 3.5 Safety Docs/Lockouts/Clearance, 3.6 Reactive Service Calls, 3.7 Spare Parts & Obsolescence, 3.8 Downtime/Credits/Reconciliation, 3.9 Fleet Condition & Renewal Pricing
- §4 Endpoint Definitions (4-column table, 65 rows)
- §5 Error Code Catalogue (2-column table, 62 rows)

## Coverage (machine-verified against SCAFFOLD.yaml)
- **Endpoints 65/65** (§4 table row count exact; all also narrated in §3).
- **Errors 62/62** — every `ERR_*` id backticked in prose and present in §5 with its status (409×26, 422×17, 404×12, 403×4, 401, 400, 412).
- **Validations 63/63** — §2.9 carries every priority 1–63 in ascending order with error id, HTTP status and applies_to scope.
- **Calculations 15/15**, including all 31 constant blocks: every numeric constant value appears in the prose (verified by script; the one gap found, `PM_OVERDUE_FACTOR`, was rewritten from "one and a quarter times" to an explicit `1.25`).
- **State machines 9/9, 46/46 transitions** — ServiceContract (§3.2+§3.9), ServiceCall incl. the ON_SITE↔PARTS_HOLD cycle (§3.6), PreventiveVisit both dimensions (§3.4 / §3.5), Equipment (§3.5), DowntimeEvent (§3.8), TechnicianAssignment (§3.3), PartOrder (§3.7), RenewalQuote (§3.9), PartCatalogEntry (§3.7).
- **Roles 6/6**; **path variables 13/13**; **enum values 41/41** backticked.

## Hard Contract reports
- **Contract 1 — Field-Name Coverage: PASS.** Pass 1: all 171 identifiers (every `entities[].fields[].name`, nested element name, endpoint `input`, query/path param, and computed-read output key) appear verbatim in backticks — zero missing. Pass 2: entity names, enum values, error ids and path variables all present. Pass 1 initially flagged 5 renewal fields that existed only inside backticked formulas; a sentence was added to §3.9 naming `quoted_base_cents`, `parts_surcharge_cents`, `history_load_pct`, `history_surcharge_cents`, `subtotal_cents`, `compliance_discount_pct`, `compliance_discount_cents`, `quoted_annual_cents`, `fleet_age_index`, `sla_breach_count`, `critical_call_count`, `pm_compliance_pct_snapshot`, `floor_applied`, `cap_applied` as standalone stored fields.
- **Contract 2 — Rule Coverage: PASS.** (1) 63/63 validations with priority. (2) Both OCC rules (renewal-quote issue, credit reconciliation) on `expected_contract_version` / `ERR_STALE_CONTRACT_VERSION` 412 in §2.8 and restated at rung 20. (3) 46/46 transitions with actors, preconditions and side effects. (4) 15/15 calculations with formulas, constants, precision and both dual-variant pairs given equal density. (5) Every validation condition tied to its error id. (6) Endpoint side_effects rendered as causal cascades (the 5-hop resolve cascade, the 3-hop EOS cascade, the 3-hop suspend teardown). (7) Structured fields (`checklist_template`, `checklist`, `line_items`) specified element-by-element. (8) Sibling symmetry held: OPEN-vs-DISPATCHED cancel, ANNOUNCED-vs-OBSOLETE declaration, accept-vs-decline, cancel-vs-mark-missed, and the OPEN/CLOSED/RECONCILED waive branches.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path (script-verified). Paths appear only in §4; §2 mentions only the `/fleetcare` prefix.

## Zero-Silence-Rule notes (scaffold conflicts resolved)
1. `RenewalQuote.sla_breach_count` / `critical_call_count`: the entity field descriptions require `status == RESOLVED` and `reported_at` in `[term_start_date 00:00:00Z, issued_at)`, while `renewal_quote_pricing`'s formula/`input_set` omits both qualifiers. **Followed the entity field descriptions** (both counts scoped to RESOLVED calls in the term-start-to-issue window) as the more specific and mutually consistent statement.
2. `Equipment.usage_hours` precision: field constraint says one decimal place, `pm_status_evaluation.precision` says 2 decimals round_half_up, creation defaults to `0.00`. **Specified two decimal places, round half up.**
3. Checklist element `result` has no declared enum (`PENDING` as seed, `FAIL` used in rules). **Specified `PASS`/`FAIL` as the recordable values with `PENDING` as the unrecorded seed.**
4. Equipment tag-out takes `reason` but the state machine says the transition records `INSPECTOR_TAG_OUT`. **Specified that `reason` must be one of the four declared `safety_lockout_reason` values and is stored verbatim, with `INSPECTOR_TAG_OUT` being what a direct inspector tag-out records** — consistent with both readings.
5. Specified without explicit scaffold backing (needed for a closed contract): `version` starts at 1 and increments on every mutation including cascades; `pm_visits_per_year` is *not* enforced as a scheduling cap (stated explicitly so the implementer does not invent one).

**Orchestrator verification:** independently confirmed PRD.md ends at the final row of the §5 error table (a real section boundary, not mid-sentence); §4 table holds 65 endpoint rows and §5 holds 62 error rows; a script cross-check found 0 scaffold error codes and 0 scaffold endpoint paths missing from the prose. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T17:00:00.000Z

Stage 2 generation is complete and audited.

## Outputs (all at the task root, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/test_helpers/` — 2372 lines: `__init__.py` 154, `api_client.py` 682, `api_errors.py` 159, `assertions.py` 265, `constants.py` 202, `factories.py` 392, `fixtures.py` 387, `test_users.py` 93, `types.py` 38.

`/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/test_suite/` — 10164 lines: `conftest.py` 21, then `test_01` 388, `test_02` 468, `test_03` 454, `test_04` 459, `test_05` 354, `test_06` 321, `test_07` 339, `test_08` 290, `test_09` 397, `test_10` 755, `test_11` 1016, `test_12` 1383, `test_13` 967, `test_14` 902, `test_15` 500, `test_16` 116, `test_17` 512, `test_18` 380, `test_19` 142.

## Coverage

**116 test functions** (more collected cases — several are parametrized rung/boundary/role tables). **79 of 79 non-stub design instances translated; zero skipped.**

- Queue A (§1.8): 18/18 instances, exactly 2 tests each (40 tests across `test_01`–`test_09`, including one 2-row parametrize).
- Queue B (§1.9): 61/61 non-stub instances (76 tests across `test_10`–`test_19`). All 18 `excluded_because` stubs were left untranslated and no tag names one.

## Audit results

- Every test carries **exactly one** `Design:` line, and it is the last non-blank line of its docstring; every tag resolves to a real non-stub instance name (verified by AST walk against tag lists extracted from both yamls).
- All **128 quoted PRD citations verified verbatim** against `workspace/PRD.md` by whitespace-normalized substring match; every test has at least one long citation. No `skip`/`xfail` markers, no scaffold vocabulary anywhere.
- `python3 -m compileall -q` silent on both directories; all 19 test modules import cleanly with every helper name resolving; pyflakes reports zero undefined names and zero unused imports in the test files. `__pycache__` cleaned. Nothing named `test_helpers`/`test_suite` exists under `workspace/`. pytest was never run and no server was started.

## Fixes and gaps worth relaying

1. **Stage 1 bug I fixed:** `club_payload` and `technician_payload` defaulted `region_code` to `"NORTH"` (5 letters) while §3.1 requires two to four uppercase letters — every club/technician creation would have failed `ERR_INVALID_REQUEST`. Defaults are now `"NW"`, and I normalized all 46 explicit `"NORTH"`/`"SOUTH"` literals in the generated tests to `"NW"`/`"SW"` (region-mismatch scenarios still use distinct codes).
2. **Design-index payloads corrected to the PRD** (outcome-neutral): part categories `MECHANICAL`/`ASSEMBLY` → `STRUCTURAL`, `COSMETIC` → `CONSUMABLE`; free-text tag-out reasons (`"DECK_HAZARD"`, `"Frayed handrail webbing"`, `"Handrail sensor intermittent"`) → the declared `INSPECTOR_TAG_OUT`.
3. **Two design-index errors found and overridden in favour of the PRD:** an instance asserting `health_score == 98.00` for a 2024-03-01 install read at 2026-08-15 (897 days floors to 2 age years, so the PRD gives 96.00), and a routing instance asserting assignments are `CONFIRMED` after dispatch (§3.3/§3.6 say `RESERVED` until arrival).
4. **Assertions dropped for non-derivability** (instances still translated): `PartOrder.unit_cents` and `covered_cents` (§3.7 presents them as intermediate computations, not declared persisted fields — the stated `draw + billable == list_total` identity is asserted instead); `injury_reported`'s default when omitted; absolute `version` integers on multi-hop cascades (asserted as strictly-increasing instead); pre-reconciliation nullability of `final_credit_cents`; `response_minutes` null on an OPEN call; `release_reason` on the declined-quote teardown path.
5. One list-ordering recipe created three rows under a single frozen clock instant, leaving `created_at` ascending order and the `offset=2` window underdetermined; the test advances the logical clock one minute between registrations so the assertion is uniquely PRD-derived.

## Step 6: Generate Implementation — 2026-09-04T17:00:30.000Z

Implementation is complete, byte-compiles cleanly, and smoke-tests green.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/workspace/implementation/`)

| File | Lines |
| --- | --- |
| `app.py` | 89 |
| `db.py` | 140 |
| `errors.py` | 89 |
| `middleware.py` | 71 |
| `response.py` | 132 |
| `routes/clock.py` | 19 |
| `routes/clubs.py` | 51 |
| `routes/models.py` | 52 |
| `routes/equipment.py` | 109 |
| `routes/contracts.py` | 198 |
| `routes/quotes.py` | 64 |
| `routes/technicians.py` | 92 |
| `routes/visits.py` | 375 |
| `routes/calls.py` | 338 |
| `routes/parts.py` | 155 |
| `routes/downtime.py` | 44 |
| `services/calc.py` | 294 |
| `services/validate.py` | 216 |
| `services/domain.py` | 345 |
| `services/credit.py` | 155 |
| `services/quoting.py` | 135 |
| `services/parts.py` | 139 |
| `start.sh` | 10 |
| `requirements.txt` | 1 |

Total 3,313 lines (plus two empty `__init__.py` files). `python3 -m compileall -q .` → clean; no `__pycache__` left behind.

## Endpoint coverage

**65 / 65.** I diffed the PRD §4 table (65 rows) against Flask's live URL map after normalising path params: `MISSING: []`. The only extras are `GET /health` (readiness probe), Flask's default `/static/<path>`, and a defensive `POST /fleetcare/_clock/set_current_utc` alias alongside the mandated unprefixed `POST /_clock/set_current_utc`.

## start.sh

Reads `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`. `pip install` is guarded by an `import flask` probe so the per-test reboots don't re-run pip 8 rounds deep. State is pure in-memory dicts in `db.py`, empty on every boot, logical clock defaulting to `2026-08-01T00:00:00Z` — no file, no seed, no `/tmp` cache.

## Smoke test

Port 39740 was already occupied by another pipeline, so I used 47413 (probed free first) and killed only that PID / `lsof -ti :47413` — no broad pkill. Two scripted end-to-end runs, 70+ assertions, **0 failures**:

- Envelope shapes: 401 `ERR_UNAUTHENTICATED`, 403 `ERR_ROLE_FORBIDDEN`, 403 `ERR_CLUB_SCOPE_FORBIDDEN`, 200 array meta (`limit/offset/total_count/has_more`), 201 object.
- Full PM path: schedule → start → checklist (`ERR_CHECKLIST_INCOMPLETE` at the right rung) → complete → safety-doc submit/certify → `pm_credit_earned: true`.
- Full call path: GOLD/CRITICAL `sla_target_minutes: 60`, `ERR_DUPLICATE_OPEN_CALL`, dispatch, arrive (`response_minutes: 45`, `sla_met: true`), parts-hold (3333 → 6666 list, 5000 draw / 1666 billable against a 5000 allowance), `ERR_UNRESOLVED_PART_ORDER`, install, resume, resolve.
- Verified arithmetic: downtime 840 min → provisional 17600 (GOLD grace 180 @1600/h); reconciliation posted 17600, forgone 0, contract version +1; quote 148500 base (age 1.35 × condition 1.10) + 26730 parts + 2228 history − 5% compliance → floored to 1080000 with `floor_applied: true`.
- Safety band: `ERR_INJURY_SEVERITY_MISMATCH`, injury → `TAGGED_OUT/MEMBER_INJURY` + club lockout count 1, `ERR_SAFETY_CERTIFICATION_REQUIRED` for a non-inspector on a locked-out machine, `ERR_SAFETY_CLEARANCE_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`, clearance clears the lockout and stamps `last_safety_clearance_at`.
- Reversals: waiving a CLOSED event restored `credit_provisional_cents` and `downtime_minutes_ytd` to 0 and re-derived condition; second waive → `ERR_DOWNTIME_INVALID_STATE`; part-order cancel returned units to the *refurbished* bucket (1/3/0) and the full 10000 allowance; loaner swap → `list_total_cents: 0`, `loaner_active: true`, `mitigated_at` capping the event (dt 480, operating 120, provisional 0); EOS → `END_OF_SUPPORT_ANNOUNCED`, then an inventory adjustment to refurb 0 slid it to `OBSOLETE` (`ERR_INVENTORY_ADJUSTMENT_INVALID` on the over-draw).

Two PRD-internal conflicts I resolved toward the normative ladder of §2.9: dispatch checks contract-ACTIVE (rung 22) before call status (rung 23), and part-order install answers `ERR_PART_ORDER_INVALID_STATE` for a call not in `PARTS_HOLD` per rung 26 (§3.7 prose says `ERR_CALL_INVALID_STATE`; that state is unreachable in practice). `declare-end-of-support` runs the full condition refresh, matching both PRD §3.9 and the SCAFFOLD trigger list.

**Orchestrator verification:** both output trees are at the task root / workspace as specified — no `test_helpers`/`test_suite` stray under `workspace/`; `python3 -m compileall -q` clean across `test_helpers`, `test_suite` and `workspace/implementation`; 116 `def test_` functions collected across 19 test modules.

## Step 7: Run Tests and Iterate — 2026-09-04T17:52:00.000Z

Clean 8-round sweep achieved: **149/149 passing in all 8 parallel rounds** (results.1–8.json, ~273 s per round).

## Summary

**Iterations run:** 2 (iteration 1: 148/149 with 1 test failing deterministically in all 8 rounds; iteration 2: all green).

**Tests deleted:** none. No test asserted a scaffold-only or PRD-silent rule wholesale.

**Fixes applied to `test_helpers/`:** none. The single failure was not an upstream fixture bug (no shared setup-error signature; 148 other tests were green).

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on the disputed point.

**Fix applied to `test_suite/`** (STEP 2 → STEP 1c partial-coverage split):
- `test_suite/test_13_derived_calculations.py`, `test_reconciliation_filters_the_period_then_clips_at_the_annual_cap` (line ~515). The test asserted `still_open_event["period_key"] == "2026-08"` on a **still-OPEN** `DowntimeEvent`; the implementation correctly returned `null` and the test failed 8/8 with `assert None == '2026-08'`.

  PRD is explicit that `period_key` is a closure-time acquisition, not a birth field:
  - §3.7 hop one: "the call's `DowntimeEvent` moves `OPEN` → `CLOSED`, and in doing so **acquires** `ended_at` from the clock plus a computed `effective_end_at`, `downtime_minutes`, `operating_downtime_minutes`, `period_key` and `provisional_credit_cents`".
  - §3.8: "`period_key` is the `YYYY-MM` of `effective_end_at`" — a field that only exists after closure.
  - Creation (§3.7) enumerates the birth fields exhaustively and omits `period_key`: "one `DowntimeEvent` is created in status `OPEN` with `started_at` equal to `reported_at` and with `contract_id`, `equipment_id` and `service_call_id` copied from the call".

  The assertion was therefore uncovered by PRD (and directly contradicted by it). I kept the covered assertion (`status == "OPEN"`, which is the exclusion criterion the test actually exercises — the candidate set is "status exactly `CLOSED`") and replaced the uncovered one with a PRD-derived equivalent that preserves the "in the target month" intent: `still_open_event["started_at"].startswith("2026-08")`, resting on the verbatim rule that creation sets `started_at` equal to the clock-stamped `reported_at`. No assertion was weakened to an HTTP-status check, no skip/xfail added, and the remaining discriminating assertions (`reconciled_event_count == 2`, and the open event still reading `OPEN` after reconciliation) are untouched.

Only one `period_key` assertion in the whole suite targeted an OPEN row; the other eight all sit on `CLOSED`/`RECONCILED` rows or on `last_reconciled_period_key`, so no companion fixes were needed. `worklog.md` untouched; stray manual server on port 17402 killed (killed by port, never a broad pkill).

**Orchestrator verification:** read all 8 `results.$i.json` directly — every round reports `passed == total == 149`. Sweep artifacts are present on disk (not a phantom clean run). Step 8 is NOT skipped: the skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes; there was 1 `test_suite/` fix, so Step 8 runs with that item as its focus list.

## Step 8: Finalize PRD — 2026-09-04T17:56:00.000Z

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2740_fitness_equipment_service_maintenance_contract/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 516 → PRD_FINALIZED.md 516 lines (0.00% line delta; one line revised in place, +1,014 chars ≈ +0.6% by bytes).

## Changes (1)

- **§3.6 (Reactive Service Calls — call-creation consequences, line 285)** — *revise* — after the existing sentence that lists the newborn `DowntimeEvent`'s four birth fields, pinned that `ended_at`, `mitigated_at`, `effective_end_at`, `downtime_minutes`, `operating_downtime_minutes`, `period_key`, `provisional_credit_cents`, `final_credit_cents`, `posted_credit_cents` and `waive_reason` are all present on the row but read null while the event is `OPEN`, and named the single later step that populates each; explicitly stated that `period_key` is a closure-time acquisition, so an `OPEN` event's `period_key` is null rather than the `YYYY-MM` of `started_at`. — `implementation/services/credit.py:8-27` (birth nulls), `:52-60` (closure fields), `:116-120` (reconciliation fields), `:82` (`waive_reason`), `implementation/services/parts.py:90` (`mitigated_at`).

This is the one genuine PRD silence behind the Step 7 item. The Step 7 fix itself was a test bug (the suite asserted `period_key == "2026-08"` on an OPEN event), but the PRD never said what an OPEN event's closure-time fields read before closure — it only enumerated the birth fields and defined `period_key` in terms of `effective_end_at`. A fresh implementer could legitimately have seeded `period_key` from `started_at`. That gap is now closed; no other edit was warranted.

## Per-edit pre-edit search log

**Edit 1**
- **(a) Subject identified:** the field-by-field value state of a `DowntimeEvent` row at birth and at each subsequent transition — specifically which step writes each closure-time / reconciliation-time / waiver-time field, and what those fields read before that step.
- **(b) Impl paths enumerated (read or grepped):**
  - `grep -rn "period_key" --include=*.py implementation/` → 12 hits: `services/credit.py:23,58,93,99,131,134`, `services/calc.py:143` (`period_key_of`), `services/validate.py:151`, `routes/downtime.py:21` (list filter), `routes/contracts.py:62,154,160,166,171`.
  - `services/credit.py` read in full: `open_event` (all ten fields seeded `None`), `close_event` (writes exactly `status`, `ended_at`, `effective_end_at`, `downtime_minutes`, `operating_downtime_minutes`, `period_key`, `provisional_credit_cents` — notably *not* `final_credit_cents`/`posted_credit_cents`), `waive_event` (writes only `status` + `waive_reason`; reversal branch guarded on prior `CLOSED`/`RECONCILED`, so the OPEN→WAIVED path leaves every computed field null, matching §3.8's existing "no credit fields were ever populated"), `reconcile_period` (writes `final_credit_cents`, `posted_credit_cents` only), `credit_summary`.
  - `grep -rn "mitigated_at" --include=*.py implementation/` → `services/parts.py:90` is the *only* writer, and it is scoped to `credit.event_for_call(call["id"], statuses=("OPEN",))`, i.e. loaner install on an OPEN event only — consistent with §3.7's existing wording and with my "from a loaner installation".
  - `db.py:88` `base_row()` → confirms the common properties are exactly `id`/`created_at`/`updated_at`/`version` plus a private `_seq`; `response.py:28` `scrub()` drops `_`-prefixed keys, so the row's public field set is exactly the four birth fields + `status` + the ten nulls. This validates the completeness clause "those four are the only fields a newborn event carries a value in".
  - `routes/downtime.py` (all three endpoints) → the single read and the waive response return the raw row via `response.object_response`, so every enumerated field is visible in the response; the list endpoint's `period_key` filter is an equality match, consistent with OPEN rows carrying null.
  - Parallel PRD callsites cross-checked for contradiction: line 297 (resolution hop one — already lists the same six closure fields), line 315 (loaner `mitigated_at`), line 325 ("both credit variants sit side by side" — a claim about key presence, which my "all present on the row" preserves rather than contradicts), lines 329/335/337/341, line 446 (endpoint table).
- **(c) Wording adjustment made:** three, all to avoid a false universal.
  1. First draft said the null fields are populated "by the later transition that computes it" — but `mitigated_at` is written by a part-order install, not by a status transition of the event. Widened to "the later step that computes it" and enumerated the four distinct steps separately.
  2. First draft's completeness claim ("those are the only domain fields a newborn event carries a value in") would have been false for `status`, and ambiguous about `id`/`created_at`/`updated_at`/`version`. Re-scoped to "Apart from `status` and the common properties of §2.4, those four are the only fields…".
  3. Deliberately confined the null claim to the `OPEN` state rather than asserting anything about `final_credit_cents`/`posted_credit_cents` being null on a `CLOSED` row (true in the impl, but outside the Step 7 site and an unnecessary new universal), and phrased the `period_key` clause as "acquired at closure and nowhere else" rather than "only ever derived from `effective_end_at`", so it cannot be read as narrowing the existing §3.8 definition.

**Orchestrator verification:** `PRD_FINALIZED.md` exists, is 516 lines / 120,901 bytes (+935 bytes over PRD.md) and is NOT byte-identical to PRD.md; `diff` confirms exactly one changed line (285, §3.6). Step 8 was correctly not skipped.

## Step 9: Complete PRD — 2026-09-04T18:30:00.000Z

**Orchestrator decision (recorded per the AUTONOMY directive):** the implementation is 3,313 lines across 24 modules and the PRD is 120 KB. A single-agent whole-impl scan reliably under-scans a target this size (the known failure mode is a PRD_COMPLETED.md byte-identical to its source, i.e. the scan never really ran). I therefore ran Step 9 as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** — pass 1 performed the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 were explicitly forbidden from copying and edited the file in place. Each pass was given a disjoint implementation-module partition and the matching PRD territory, plus any findings the previous pass routed out of its own territory. Passes ran strictly sequentially (never concurrently) because they share one output file.

### Result

`workspace/PRD_COMPLETED.md` — **519 lines / 140,075 bytes**, vs source `PRD_FINALIZED.md` 516 lines / 120,901 bytes: **+3 lines, +19,174 chars (+15.9%)**, 103 changed lines. NOT byte-identical to its source. Tail is still the final row of the §5 error table; all 28 headings and all 9 `### 3.x` sections intact.

**Total: 57 changes — 39 ambiguity-pins, 18 mismatch-revisions.**

### Pass 1 — plumbing + inventory (§2 all, §3.1, §3.3, health/age/condition formulas)
Partition: `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `routes/{clock,clubs,models,equipment,technicians}.py`, `services/validate.py`, the age/usage/health/condition part of `services/calc.py`.
**24 changes — 19 ambiguity-pins, 5 mismatch-revisions:**
- §2.1 — insert — ambiguity — blank/whitespace headers count as absent; both values trimmed before use — `middleware.py:31-36`
- §2.1 — revise — mismatch — "every club-scoped read" was false: collection reads are never club-narrowed nor refused for a `ClubManager` — `middleware.py:52-55`
- §2.1 — insert — ambiguity — a `SafetyInspector` whose `X-User-ID` matches no Technician row gets `ERR_INSPECTOR_NOT_CERTIFIED` — `middleware.py:44-48`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `db.py:83-85`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not real time — `response.py:21-25`
- §2.2 — insert — ambiguity — unknown path/method still answer the envelope (`ERR_INVALID_REQUEST` under 404/405), defects answer `ERR_INTERNAL` 500 — `app.py:62-79`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected, empty value = default, no offset ceiling — `response.py:75-94`
- §2.3 — insert — ambiguity — `created_at` ties (routine under a frozen clock) break by insertion order — `db.py:119-123`
- §2.3 — insert — ambiguity — filters are exact case-sensitive equality, empty = absent, unmatched value ⇒ empty page (not 400), boolean-filter literals, unknown params ignored — `response.py:105-132`
- §2.4 — insert — mismatch — a write leaving every field unchanged does **not** move `updated_at`/`version`; the four ledger writes (allowance adjustment incl. 0¢, reconciliation, quote issuance, checklist recording) always bump — `db.py:107-116`, `contracts.py:145`, `credit.py:132`, `quoting.py:119`, `visits.py:220`
- §2.5 — insert — ambiguity — instants held at full precision but rendered truncated to 3 fractional digits — `db.py:46-54`
- §2.6 — insert — ambiguity — trailing slash addresses the same path — `app.py:47`
- §2.7 — insert — ambiguity — a monetary body field must be a JSON integer (`1000.0`/`"1000"` are 400) — `validate.py:55-67`
- §2.7 — insert — ambiguity — 2-dp values serialise as JSON numbers, so `48.00` prints `48.0` — `response.py:28-36`
- §2.8 — insert — ambiguity — `expected_contract_version` must be an integer ≥ 0; malformed/negative is 400 at rung 18, before comparison — `validate.py:214-216`
- §2.9 rung 3 — revise — mismatch — scope outranks existence only on the club read; elsewhere the row must be found first, so a missing row answers its 404 — `clubs.py:50` vs `equipment.py:72-73`
- §2.9 rung 18 — insert — ambiguity — absent body = empty object, non-object body = 400, JSON `null` == omitted, strict types (no coercion), accepted instant forms normalised to UTC — `middleware.py:64-71`, `validate.py:18-123`
- §2.9 rung 33 — revise — mismatch — `ERR_SAFETY_CERTIFICATION_REQUIRED` fires only for an explicitly named technician; routing drops non-inspectors and reports `ERR_NO_ELIGIBLE_TECHNICIAN` — `calls.py:148-158`, `domain.py:261`
- §3.1 — revise — mismatch — `model_code` is **not** unique within a manufacturer (no check exists, and no error code for it) — `models.py:12-37`
- §3.1 — insert — ambiguity — `base_annual_service_cents` may be zero — `models.py:22`
- §3.1 — insert — ambiguity — `install_date` must be a real calendar day, a future date is accepted; serial uniqueness is exact case-sensitive and checked after both body refs resolve — `equipment.py:20-28`, `validate.py:126-139`
- §3.1 — insert — ambiguity — 2-dp rounding precedes the monotonicity comparison, so `1000.004` over `1000.00` is a confirmation not a regression — `equipment.py:84-86`
- §3.9 — insert — ambiguity — `age_years` clamps at 0 for a future `install_date` (and everywhere whole years are derived) — `calc.py:133-140`
- §3.9 — insert — ambiguity — the fleet roll-up refreshes **every** contract of the club whatever its status, in `created_at` order — `domain.py:175-178`

Pass 1 routed two §3.5 findings (safety territory) to pass 2: `equipment.py:101-103` storing the supplied `reason` verbatim vs the PRD's `INSPECTOR_TAG_OUT` claim, and tag-out having no state precondition in the impl.

### Pass 2 — contracts, visits, safety (§3.2, §3.4, §3.5)
Partition: `routes/contracts.py`, `routes/visits.py`, `services/domain.py`, the PM-compliance/SLA-target part of `services/calc.py`. 519 lines / 128,206 B → 519 lines / 134,214 B (+6,008).
**15 changes — 8 ambiguity-pins, 7 mismatch-revisions:**
- §3.2 — insert — ambiguity — term-ordering violation is a rung-18 `ERR_INVALID_REQUEST` (400), reported *before* `club_id` resolution — `routes/contracts.py:31-34`
- §3.2 — revise — mismatch — "a `GOLD` agreement is always sold with `FULL` inclusion" was false; `SILVER`/`GOLD` accept all three inclusions and `BRONZE`+`FULL` is the only refused pair — `routes/contracts.py:12-16,35`
- §3.2 — insert — ambiguity — `memo` is required (≥1 char) but is not persisted on the contract nor echoed — `routes/contracts.py:135`
- §3.4 — insert — ambiguity — body identifiers resolve in written order `contract_id` → `equipment_id` → `technician_id` — `routes/visits.py:55-57`
- §3.4 — insert — ambiguity — operating-window boundaries are **inclusive**; offsets measured from `window_start`'s own UTC midnight with the close offset = open offset + span, so a midnight-crossing window can never pass — `routes/visits.py:19-25`
- §3.4 — revise — ambiguity — copied checklist elements seed `note` to null and `consumable_replaced` to `false` — `routes/visits.py:92-99`
- §3.4 — insert — ambiguity — a visit **may be booked** against a `TAGGED_OUT` machine (lockout checked only at start); named technician needs no inspector credential, only automatic routing narrows to inspectors — `routes/visits.py:59-87,180`
- §3.4 — insert — ambiguity — `consumable_replaced` defaults `false`, `note` defaults null (empty string allowed), and both defaults are re-applied on every recording, so an omitting re-record clears them — `routes/visits.py:201-217`
- §3.4 — revise — mismatch — safety-critical FAIL tag-out is applied whatever the current `lifecycle_status`, overwrites any prior reason, the counter is a recount (unchanged if already `TAGGED_OUT`), and it does **not** raise `safety_review_required` on open calls — `routes/visits.py:225-228`, `services/domain.py:199-205`
- §3.4 — revise — mismatch — completion guards evaluate **safety first** (rung 36) then `ERR_CHECKLIST_INCOMPLETE` (rung 52); PRD prose had them in the reverse order, which is decidable and wrong for a visit that is both incomplete and carrying a critical FAIL — `routes/visits.py:239-242`
- §3.4 — insert — ambiguity — completion does not re-derive `health_score`/`replacement_recommended` nor club/contract fleet counters — `routes/visits.py:246-267`
- §3.4 — insert — ambiguity — cancel/mark-missed are not gated on contract status; cancel needs `reason` ≥1 char, mark-missed takes no body — `routes/visits.py:271-300`
- §3.5 — revise — mismatch — doc rejection tags out regardless of current `lifecycle_status` (overwrites the reason), counter recounted, and does not raise `safety_review_required` on open calls — `routes/visits.py:367-374`
- §3.5 — revise — mismatch (routed finding 2) — added the `TAGGED_OUT` → `TAGGED_OUT` self-loop to the lifecycle enumeration; replaced "Every entry into `TAGGED_OUT` raises the count by one" with the **full-recount** doctrine; pinned that no lockout event has a state precondition and the most recent reason wins; pinned that only the direct inspector tag-out reaches into open calls — `services/domain.py:150-160,199-205`
- §3.5 — revise — mismatch (routed findings 1 + 2) — the supplied `reason` is stored **verbatim**; no substitution of `INSPECTOR_TAG_OUT`; tag-out has no state precondition and no invalid-state code; re-tagging an already-`TAGGED_OUT` machine answers 200, leaves the counter unchanged, and bumps `version` only if the reason differs — `routes/equipment.py:95-109`
- §3.5 — revise — mismatch — clearance: the inspector credential on `safety_clearance_technician_id` is enforced **only when `safety_review_required` is `true`**; on the reachable path where the lockout arrived after filing via a non-flag-raising cascade, any other resolvable technician lifts it — `routes/calls.py:259-263,296-301`

Pass 2 routed four items to pass 3 (§3.6 clearance verify-only, §3.8 credit-summary role set, §3.8 dual `ERR_PERIOD_ALREADY_RECONCILED` triggers, §3.9 re-quote version advance).

### Pass 3 — calls, parts, credits, quotes (§3.6, §3.7, §3.8, §3.9)
Partition: `routes/{calls,parts,downtime,quotes}.py`, `services/{credit,quoting,parts}.py`, the credit/SLA/renewal-pricing part of `services/calc.py`, and `routes/contracts.py:145-200` (reconciliation + credit-summary). 519 lines / 134,214 B → 519 lines / 140,075 B (+5,861).
**18 changes — 12 ambiguity-pins, 6 mismatch-revisions:**
- §3.6:284 — insert — ambiguity — call filing is club-scoped; the `ClubManager`'s club is resolved from `contract_id` when it resolves, else `equipment_id`, else falls through to shape/existence checks — `routes/calls.py:17-36`
- §3.6:284 — insert — ambiguity — body references resolved contract-first, machine-second, so a payload where neither resolves answers `ERR_CONTRACT_NOT_FOUND` — `routes/calls.py:50-51`
- §3.6:290 — revise — mismatch — `ERR_SAFETY_CERTIFICATION_REQUIRED` was stated as a universal for the tagged-out gate; it belongs to the named-technician path alone (ahead of region/skill/duty/calendar/capacity), while routing drops non-inspectors and reports `ERR_NO_ELIGIBLE_TECHNICIAN` — `routes/calls.py:149-158`, `services/domain.py:261`
- §3.6:298 — revise — mismatch — the segregation test was nested inside the `safety_review_required` conditional; it applies wherever a clearance is named, and an unflagged call's clearance faces no credential test yet is still resolved, stored and honoured by the lifecycle branch — `routes/calls.py:259-263`
- §3.6:300 — insert — ambiguity — when the event was already waived there is no `OPEN` event: hop one and hop two's ledger arithmetic are skipped while the lifecycle return and hops three–five still run — `routes/calls.py:282-308`
- §3.6:302 — insert — ambiguity — the single-call read (and cancel) is club-scoped; the collection read applies no confinement — `routes/calls.py:122,316` vs `106-115`
- §3.7:310 — insert — ambiguity — only `OBSOLETE` + `NEW` is refused; `ACTIVE` and `END_OF_SUPPORT_ANNOUNCED` permit all three sources — `routes/calls.py:215-216`
- §3.7:310 — insert — ambiguity — the allowance gate reads coverage alone and never `source`, so a covered `LOANER_SWAP` is refused against an exhausted allowance despite pricing at zero — `routes/calls.py:218-220`
- §3.7:318 — revise — mismatch — PRD said an install against a call outside `PARTS_HOLD` answers `ERR_CALL_INVALID_STATE`; impl answers `ERR_PART_ORDER_INVALID_STATE` for both preconditions, order status tested first — `routes/parts.py:136-139`
- §3.7:320 — insert — ambiguity — neither the part-order nor the catalogue single read is club-scoped, unlike the sibling call/event reads — `routes/parts.py:57-60,124-127`
- §3.7:322 — insert — ambiguity — the slide tests the *resulting* refurb balance (a zero/zero adjustment on an already-empty announced part completes it) while an allocation that empties the bucket does not; the declaration endpoint has no state precondition and every re-declaration re-stamps `eos_declared_at`, advances `version` and re-runs the cascade — `routes/parts.py:78-106`
- §3.8:328 — insert — ambiguity — the single-event read is club-scoped through its contract; no listing in the spec applies club confinement — `routes/downtime.py:27-30`
- §3.8:336 — revise — mismatch — "always worth strictly less finally than provisionally" is a false universal; final is never larger and is strictly smaller only when the wall-clock span exceeded grace (both are `0` otherwise) — `services/credit.py:51,109`, `services/calc.py:244-250`
- §3.8:338 — insert — ambiguity — an empty candidate set shares the one `ERR_PERIOD_ALREADY_RECONCILED`, is not a zero-event success, and moves no ledger field — `routes/contracts.py:162-169`
- §3.9:348 — revise — mismatch — the condition re-derivation trigger list was incomplete: adds the inventory adjustment completing a critical spare's slide, and narrows the waiver trigger to the `CLOSED`/`RECONCILED` branches — `services/parts.py:131`, `services/credit.py:84-89`
- §3.9:376 — insert — ambiguity — `decline_reason` present-and-null on an `ISSUED` quote; single-quote read club-scoped, listing not — `services/quoting.py:107`, `routes/quotes.py:22-27`
- §3.9:378 — revise — ambiguity — "transacted as a new contract row" could read as this endpoint creating one; accept creates nothing and leaves the `SCHEDULED` visits and reservations standing — `routes/quotes.py:46-48`
- §3.9:378 — insert — ambiguity — released assignments carry `release_reason` `CONTRACT_EXPIRED`; non-`SCHEDULED` visits and open calls untouched (mirrors §3.2's suspension wording) — `services/quoting.py:123-136`, `services/domain.py:326-335`

Disposition of the four routed items: §3.6:298 clearance credential — verified, kept (pass 3 did edit the *adjacent* segregation clause, a separate defect); §3.8 credit-summary — verified, no change needed (three-role restriction and computed field set already pinned); §3.8 dual reconciliation triggers — **edited** (prose was silent on the empty-period case); §3.9 re-quote version advance — verified, no change needed.

### Orchestrator verification
- `PRD_COMPLETED.md` exists at 519 lines / 140,075 bytes and is **not** byte-identical to `PRD_FINALIZED.md` (103 changed lines) — the scan genuinely ran in all three passes, and each pass's edits survive its successors.
- Tail is the final row of the §5 error table; 28 headings and all 9 `### 3.x` business-logic sections intact.
- No `.py` file under `workspace/implementation/` was modified after `results.1.json` was written, so the green 8-round sweep (149/149 × 8) still describes the shipped implementation. Step 9 touched documentation only.

**Pipeline complete through Step 9.**
