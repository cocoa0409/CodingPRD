# Worklog — task_2561_keg_pool_tracking_asset_recovery

> Note (orchestrator): the Step 1 worklog entry and the empty `workspace/` directory were
> removed from disk at some point during Step 2 (the task directory's mtime shows a 13:35
> rewrite, and only the three scaffold YAMLs survived). The orchestrator recreated
> `workspace/` and reconstructed the Step 1 entry below from its own record. No scaffold
> content was affected — all three YAMLs verified present with correct top-level keys.
> From Step 3 onward this file is strictly append-only.

## Step 1: Create task directory — 2026-09-03T10:34:41.863Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2561_keg_pool_tracking_asset_recovery` and its `workspace/` subdirectory. Index 2561 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T13:36:00.000Z

Done. All three scaffold artifacts are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2561_keg_pool_tracking_asset_recovery/`

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3711 | §1.0–§1.7 only (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) — neither design key present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2708 | single key `scaffold_difficulty_design` — 9 rules / 18 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6988 | single key `scaffold_corner_design` — 9 sections / 104 instances |

## §1.0–§1.7 surface

14 entities (graph topology, many-to-many + self-referential + polymorphic + cross-aggregate), 11 state machines / 85 transitions (cyclic: quarantine→retest loop, evidence-hold→resume), 3 OCC concurrency rules + a pinned version-semantics block, 16 calculations (2 dual-variant, 4 conserved-quantity invariants), 51 ordered validations, 56 endpoints, 67 error codes, 5 roles under `role_model: segregation_of_duties`. Profile: `expert_plus`, quota_allocation + event_sourcing, layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers], `consistency_model: immediate`.

## §1.9 corner design

104 instances: entities 14, state_machines 16, calculations 18, validations 13, endpoints 8, errors 18 (all `claim_type: triggerable`), rbac 8, Cross-Cutting Complexity Layers 7, Consistency Model 2. 79 full instances + 25 `excluded_because` stubs, each citing an existing §1.8 instance name; all names unique across both design files; every claim_type is a row of its section's table in `references/claim-extraction-guide.md`.

## Design adjudications recorded in the §1.5 audit header (18 total; 4 made in this final pass)

- **REVERSE un-probation was too broad** — it lifted PROBATION for any brewer whose balance fell below 25000, which would erase a probation the loss-rate gate forced (that brewer's balance is under 25000 the whole time). Now conditioned on `status_reason == CHARGEBACK_BALANCE_THRESHOLD`: a reversal only undoes the gate it tripped, and the loss counters are never recomputed by a money event.
- **SETTLE/REVERSE role split had no error code** — it existed only as a §1.2 precondition, and priority 2 cannot enforce it (both roles are on the endpoint; the split depends on `payload.action`). Validation priority 26 gained clause (b): a role/action mismatch on `chargeback-resolution` is `ERR_SEGREGATION_OF_DUTIES` 403, after priority 10 and before priority 51.
- **`POST /service-cycles` performed an undeclared custody move** ("moves to IN_SERVICE if it is not already"). §1.2 gained the `IN_FLOAT -> IN_SERVICE` recertification-pull edge (the only intake that lowers `available_pct`), priority 10 now judges `custody_state IN {IN_FLOAT, IN_SERVICE}` for that endpoint, and a keg already IN_SERVICE is booked with no census move.
- **No-op cascade recomputes had undefined version behaviour** — §1.2.1 now pins "a recompute bumps a row only when it changes a stored field of that row", which is what makes every `expected_*_version` literal countable (exercised directly by the fleet-import cascade instance: nine imports leave the agreement at version 2).

Lint: `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2561_keg_pool_tracking_asset_recovery`

```
Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     79
  Calls scanned (§1.8+§1.9):  1514

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read at any point; the scaffold comes solely from the scenario text plus the generator skill's specification.

## Step 3: Copy shared files — 2026-09-03T13:36:02.424Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). Also recreated `workspace/`, which had gone missing during Step 2 (see note at top of file).

## Step 4: Generate PRD — 2026-09-03T13:56:31.873Z

PRD generation for task 2561 is complete.

**Output**: `workspace/PRD.md` — 561 lines, 125 KB, built by 13 chunked heredoc appends plus two small `Edit` refinements. Nothing else in the task directory was created, modified or deleted (`worklog.md`, `INSTRUCTION.md` and the three SCAFFOLD files are untouched). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced.

**Section inventory** (last heading is `## 5. Error Codes`, file ends on the final error-table row):
- §1 Introduction
- §2 Global Specifications (11 subsections): 2.1 RBAC · 2.2 Response Structure (verbatim) · 2.3 Pagination · 2.4 Identity/Timestamps/Version Counters · 2.5 The Logical Clock · 2.6 Money, Basis Points and Rounding · 2.7 Stale-Version Guards · 2.8 Request Admission and the Order of Judgement (full 51-step ladder) · 2.9 Conserved Quantities and Cascade Propagation · 2.10 Two Deliberately Different Interval Rules · 2.11 Reference Vocabularies
- §3 Business Logic (10 subsections): 3.1 Onboarding + stainless index · 3.2 Pools, fleet import, posture gate · 3.3 Float agreements and float posture · 3.4 Issuance orders · 3.5 Scan stream and fill billing · 3.6 Trade-side custody, dwell, incentives, sweep · 3.7 Misdelivery reconciliation · 3.8 Service line · 3.9 Loss assessment and chargeback ledger · 3.10 Theft investigation and write-off
- §4 API Endpoints — 56 rows, exactly 4 columns
- §5 Error Codes — 67 rows, exactly 2 columns

**Contract reports**
- **Contract 1 (Field-Name Coverage): PASS** — 178/178 required identifiers (all `entities[].fields[].name`, all endpoint `input` fields, all query params, all 13 path params) appear verbatim in backticks; two independent passes. All 67 error IDs and all 79 enum members/state names also verified present in backticks.
- **Contract 2 (Rule Coverage): PASS** — all 51 validations rendered as an explicit 1-to-51 precedence ladder in §2.8 with `applies_to` scopes, plus their substantive conditions restated at their workflows; all three priority-pair callouts (12 over 50, 20 over 27, 26 over 51); all 11 state machines and their 84 transitions with preconditions and side effects; all 16 calculations with constants and worked examples (fill charge 2200→2640/2167/4807, incentive 250·SILVER→288/173/72=533 vs 532, depreciated book 12000/40 fills→9840 gross/5904 net, loss rate 1-in-3→3333 bp); all 3 OCC rules; the single-bump and no-op-recompute version semantics; all three conserved-quantity invariants with both halves of each compensating pair; sibling-branch symmetry (ALLOCATED/PARTIALLY_ALLOCATED, UPHELD/WAIVED, RECOVERED/WRITTEN_OFF, both quarantine reasons, both intake variants of service booking).
- **Contract 3 (§3 Path Purity): PASS** — 361 distinct backtick tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combinations; also zero un-backticked raw path strings anywhere in §1–§3.
- §2.2 verified byte-identical to `section-2.2-response-structure.md`. No fuzzy quantifiers and no pseudocode operators (`==`, `+=`, `>=`, `IN {…}`, `round_half_up`) survive anywhere in the prose.

**Coverage notes**
1. **Scaffold self-contradiction on `kegs_issued_count`.** The `FloatAgreement` field description defines it over orders in `{ALLOCATED, PARTIALLY_ALLOCATED, DISPATCHED}`, while the `float_posture` calculation defines it as `status = DISPATCHED` only. I rendered the three-status (entity-field) reading, because the allocate operation's side effects explicitly recompute `kegs_issued_count` and that recompute would be a guaranteed no-op under the DISPATCHED-only reading. Implementers/test authors should be aware the scaffold is ambiguous here.
2. **`DEPRECIATED_BOOK` floor never binds.** The 7000-basis-point depreciation cap leaves exactly 30 percent of replacement cost, which equals `BOOK_VALUE_FLOOR_PCT`, so the "greater of book value and floor" always resolves to the book value (they tie at the cap). I stated both clauses faithfully without asserting the redundancy.
3. **Seven path-parameter names** (`accrual_id`, `assessment_id`, `center_id`, `cycle_id`, `investigation_id`, `order_id`, `scan_event_id`) occur in the scaffold only inside paths. Since §3 forbids path tokens, I listed them explicitly in the §4 intro paragraph so each is individually backticked somewhere.
4. **§3 has 10 subsections**, one above the skill's suggested 5–9 range; deliberate, given 56 endpoints and 14 entities. §2 has 11, inside the suggested 8–12.
5. Two hard-to-render rule pairs got explicit "must not be unified" prose: the strict-greater-than dwell-flag limit versus the inclusive dwell-band table, and the half-open exclusive-end custody intervals versus the closed-at-both-ends service intake windows.
6. Verification tooling caveat: a naive backtick-pair regex mis-pairs across the ```json fences in §2.2 and reports mass false negatives on Contract 1. Strip fenced blocks first — the initial "156 missing" reading was a checker artifact, not a document defect.

**Orchestrator anti-truncation check**: independently verified. `PRD.md` is 561 lines, headings are §1–§5 in order, the §4 endpoint table holds 58 rows (header + separator + 56 endpoints), the §5 error table holds 67 `ERR_*` rows, and the file's last line is a complete table row (`| \`ERR_CREDIT_LIMIT_EXCEEDED\` | 402 |`). Ends at a real section boundary — not truncated, no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T14:35:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first and is recorded first. Step 6's spawn preceded the creation of `test_suite/` on disk, and the subagent was additionally given an explicit hard-isolation constraint forbidding any read of `test_helpers/`, `test_suite/`, or either design YAML.)

The implementation is complete.

## Files written (all under `workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` (executable) | 8 |
| `requirements.txt` | 1 |
| `app.py` | 54 |
| `clock.py` | 21 |
| `db.py` | 31 |
| `errors.py` | 94 |
| `response.py` | 77 |
| `util.py` | 304 |
| `middleware.py` | 97 |
| `services/calc.py` | 281 |
| `services/recompute.py` | 285 |
| `services/view.py` | 39 |
| `routes/parties.py` | 217 |
| `routes/pools.py` | 272 |
| `routes/floats.py` | 365 |
| `routes/scans.py` | 305 |
| `routes/service.py` | 307 |
| `routes/recovery.py` | 721 |
| **total** | **3479** |

## Endpoints: 56 of 56

A programmatic diff of Flask's `url_map` against every `method:`/`path:` pair in SCAFFOLD.yaml reports `missing: []`, `extra: []`.

## Organization

`app.py` → `create_app()` registers six blueprints and installs `ApiError`/404/405/500 handlers so every response (including method-not-allowed) is a proper envelope. Layers: `clock.py` (settable logical clock, default `2026-08-01T00:00:00Z`), `errors.py` (all 67 error IDs → HTTP status), `response.py` (meta/envelope/pagination), `util.py` (instant parsing, floor-day arithmetic, ROUND_HALF_UP helpers, one-bump-per-row-per-request `bump`/`apply_changes`, shape validators), `middleware.py` (ladder steps 1–3, 5, 8), `services/` (pure `calc`, derived-state `recompute` with the full cascade chain, `view` projection/paging), `routes/` (parties, pools, floats, scans, service, recovery). Storage is `db.py`: fourteen plain dicts, no seeding, no disk, no SQLite.

## Smoke tests

Two scripted end-to-end passes over fresh processes on high random ports (`kill <captured pid>` only, never `pkill`). Pass 1 (46 calls): onboarding → pool + 6 kegs → agreement activate → order → allocate → dispatch → FILL/DISTRIBUTION/RETAIL/RETURN scans → incentive accrual + pay → service line (short caustic 422, release-by-tester 403, release) → assessment with stale-version 412, wrong-brewer dispute 403, `ERR_ASSESSMENT_ALREADY_OPEN`, self-resolve 403, uphold cascade → probation → agreement `SUSPENDED` → keg `LOST` → settle-mismatch 422 → analyst-SETTLE 403 → reverse → misdelivery claim (already-open 409, out-of-turn 409, counter, agree, offset accrual) → theft investigation (unattached 409, hold, resume with census restored, write-off → `STOLEN` + clawback with service history preserved) → pagination/envelope/role/404 checks. **0 mismatches.** Pass 2 hit the remaining endpoints (status override, cooperation agreement, index list, agreement/order lists + cancel + terminate, sweep, dwell read, scan-event and cycle lists, waive, recovered close, plus empty-collection checks proving a fresh process holds no data). **0 mismatches** apart from one wrong expectation in my own script (`DELETE /pools` returns 405 with an `ERR_INVALID_REQUEST` envelope, which is the intended design).

## PRD ambiguities resolved

- **Terminal before invalid-state.** For the row whose own dimension moves, `ERR_ALREADY_TERMINAL` is tested before `ERR_INVALID_STATE`; otherwise it would be unreachable for orders, claims, assessments, chargebacks, investigations and agreements.
- **Shape (step 4) before path resolution (step 6)**, per the numbered ladder; §2.8's "pool resolved before the body" prose read as ordering path IDs ahead of *body FK* resolution (step 7).
- **Service booking from a written-off keg** → `ERR_INVALID_STATE` (§3.8's explicit "every other custody state" prose beats step 11).
- **Agreement activate**: `TERMINATED` → `ERR_ALREADY_TERMINAL`, own row `ACTIVE` → `ERR_INVALID_STATE`, a *different* ACTIVE agreement on the pair → `ERR_AGREEMENT_ALREADY_ACTIVE`.
- **Release from `QUARANTINED`**: reason `INSPECTION_MAJOR_DEFECT` → `ERR_QUARANTINE_RELEASE_BLOCKED`; reason `PRESSURE_TEST_FAIL` → `ERR_INVALID_STATE` (a passing retest is required first), which keeps step 24 reachable on both the retest and the release.
- **record-step ordering**: stage (10) → caustic/psi (22/23) → quarantine reason (24) → `occurred_at` futurity (33) → `occurred_at` vs `received_at`/`cleaned_at` ordering (`ERR_INVALID_REQUEST`, last).
- **Claim respond, wrong-side responses** (e.g. a Brewer withdrawing) → `ERR_INVALID_STATE`; turn violations → `ERR_RESPONDER_OUT_OF_TURN`; `AGREE` on a written-off keg → `ERR_ALREADY_TERMINAL`.
- **Investigation write-off close**: held kegs move to `STOLEN` and *stay attached* (so exposure keeps counting them, per the calc's `input_set`); never-held kegs detach. A `RECOVERED` close detaches everything.
- **`open_cycle_count`** is derived from open stages, refreshed via `apply_changes` on booking/release and reported live on read.
- **Cascade on every accepted scan** (`recompute.cascade_pool`), so `kegs_at_brewer_count` always matches its query definition; the no-op suppression in `apply_changes` prevents spurious version bumps.
- **Leniency choices**: list-filter enum values are not validated (an unknown value simply matches nothing); only the three `expected_*_version` fields are rejected where inapplicable; `api_request_timestamp` comes from the logical clock; lists sort stably by `created_at` ascending.

Isolation was respected: `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, listed or written, and `PRD.md`/`SCAFFOLD.yaml`/`worklog.md` were only read.

## Step 5: Generate unit tests — 2026-09-03T16:12:00.000Z

(Launched concurrently with Step 6; returned second, so it is recorded after Step 6.)

Both output directories are complete and all gates pass. Final state of task 2561's test infrastructure and suite:

## Files written

**`test_helpers/`** — 3149 lines, 9 files (complete since Stage 1, untouched this session): `fixtures.py` 1141, `types.py` 541, `assertions.py` 406, `api_client.py` 326, `factories.py` 284, `api_errors.py` 180, `constants.py` 114, `test_users.py` 108, `__init__.py` 49.

**`test_suite/`** — 12862 lines, 19 files, **200 tests**:
`conftest.py` 115 · queue A (9 files, 57 tests): `dual_variant_calc` 306/6, `combinatorial_formula` 259/6, `non_linear_state_machine` 382/6, `transitive_cascade` 424/7, `priority_pair_validation_conflict` 401/6, `boundary_precision_check` 331/6, `cross_entity_state_dependency` 334/6, `resource_temporal_overlap` 390/6, `compensating_invariant` 556/8 · queue B (9 files, 143 tests): `entities` 746/13, `state_machines` 1642/26, `calculations` 1325/22, `validations` 846/16, `endpoints` 968/19, `errors` 1592/23, `rbac` 1065/14, **`cross_cutting` 928/8**, **`consistency` 252/2**.

## Coverage against the design indices

- Queue A (§1.8): **18/18** live instances translated, 0 skipped.
- Queue B (§1.9): **78/79** live instances translated across all nine sections (entities 13/14, state_machines 13, calculations 10, validations 10, endpoints 8, errors 12, rbac 7, Cross-Cutting 4, Consistency 1). The 25 STUB entries were not translated, by design (they delegate to §1.8 owners).
- **1 skipped instance**, filter condition 2 (PRD does not uniquely derive the asserted outcome): `Corner/entities/keg_import_ignores_client_supplied_id_version_extra_field` — the PRD never states whether a client-supplied `id`/`version`/unknown field is ignored or refused.

## Verification (both mandatory final passes)

- **Citation pass:** 559 `PRD:` quotes across all 18 test files re-checked against `workspace/PRD.md` after whitespace normalisation — **BAD: 0** in every file.
- **Design-tag pass:** AST walk of all 200 test functions — every test has exactly one `Design:` line, it is the last line of the docstring, and every tag resolves to a real `name:` under a real `rule_id`/`section` in the two design yamls. **0 problems, 0 dangling tags, 0 dual tags.**
- `ast.parse` clean on all files; `pyflakes` silent on all of `test_suite/` (only barrel-export/`noqa` noise in `test_helpers/__init__.py`); `import test_helpers` OK. No server was started, no `pkill` run, nothing outside `test_helpers/` and `test_suite/` touched.

## Design claims corrected this session (PRD wins)

1. **Cross-Cutting #1** and **#4**: the design asserts `float_posture TIGHT` / `pending_replenishment_kegs 2` (resp. `3`) after kegs land at the brewer on a 4-keg float. The PRD's thin-float ceiling is `floor(4 × 20 / 100) = 0`, so any keg at the brewer reads `HEALTHY` with `pending_replenishment_kegs 0`. Asserted the PRD values.
2. **Cross-Cutting #4**: dropped the design's claim that the second FILL re-probates the brewer with `LOSS_RATE_THRESHOLD` — the PRD states the gate's condition but never scopes its *trigger* to a fill. Kept the derivable half: the fill returns 201 at a 2200-cent net charge and the trailing rate recomputes to 5000 bp over two fills.
3. **Cross-Cutting #3**: dropped `depreciation_bp` / `book_value` / `book_floor` assertions (intermediate arithmetic, not stored `LossAssessment` fields); asserted `gross_value_cents 22654` and `net_chargeback_cents 13592` versus the coerced 14100 instead.
4. **Cross-Cutting #2**: dropped the un-executed speculation about a later order exceeding `restricted_max_kegs_per_order`.

## Step 7: Run tests and iterate — 2026-09-03T18:00:00.000Z

All 8 parallel rounds are green: **200 / 200 passed in every round** (~368 s each, iteration 3's sweep).

## Summary

**Iterations run: 3** (each = one 8-round parallel `setsid nohup` sweep)
- Iteration 1 sweep: 151/200, identical in all 8 rounds (fully deterministic — no flakiness, no reaping tell, no load artifacts).
- Iteration 2 sweep: 199/200, identical in all 8 rounds (one residual failure).
- Iteration 3 sweep: **200/200 in all 8 rounds.**

**Tests deleted: none.** No test asserted a scaffold-only rule; every failure traced to a real implementation defect or a PRD-inconsistent fixture. Two *individual uncovered assertions* were removed under STEP 1c / collapse patterns (the enclosing tests were kept and still assert their PRD-covered content):
- `test_corner_state_machines.py::test_the_return_scan_closes_the_accountability_spell_and_mints_the_accrual` — dropped `current_distributor_id is None`. PRD's return-scan sentence names only `distributor_custody_started_at` as cleared; the field is cleared at service release. *Partial coverage (STEP 1c).*
- `test_difficulty_non_linear_state_machine.py::test_the_agreed_offset_pays_the_distributor_without_touching_its_returns` — dropped `tier_pct_bp is None` and `cooperation_multiplier_bp is None`. PRD §3.7 fixes only `claim_id`, `incentive_cents`, `status` on a `RECONCILIATION_OFFSET` accrual. *DEFAULT-VALUE / COMPUTED-FIELD SILENCE.*

**Fixes to `test_helpers/`: none** — all test-side corrections landed in `test_suite/` (the offending preconditions were built inline in each module's own scenario helper, not in shared fixtures/factories):
- `test_corner_validations.py` — `_two_kegs_certified_exactly_two_years_before_the_clock()` imported only 2 kegs, both then allocated ⇒ `available_pct` 0.00 < freeze 10 ⇒ pool `FROZEN` ⇒ float `SUSPENDED` ⇒ `ERR_FLOAT_SUSPENDED` at fill. Added 10 freshly certified shells (younger certification, so §3.4 ranking still issues K-0001/K-0002 first). *Fixture violated a PRD precondition; the PRD-required gate was left intact.*
- `test_difficulty_dual_variant_calc.py` — `_brewer_with_two_upheld_losses_across_two_quarters()` pinned the clock to `2026-02-01T00:00:00Z` while supplying `dispatched_at` `01:00:00Z` and fills at `02:00:00Z` ⇒ `ERR_SCAN_TIMESTAMP_FUTURE` (ladder step 33). Clock now pinned to `02:00:00Z`.
- `test_corner_errors.py` (3 tests) — hard-coded `fill_count == 0` / `== 1` against `KEG_SPECS_TWO`/`THREE`, which seed `fill_count` 5 and 6; §3.4 ranks by `fill_count` ascending, so `allocated_keg_ids[1]` is the seeded keg. Now captures `fills_before` and asserts the delta.
- `test_corner_endpoints.py::test_the_sweep_reports_the_recomputed_postures_without_moving_anything` — expected `HEALTHY`/empty/0, but §3.3's ceiling `floor(2 * 20 / 100) = 0` with `kegs_at_brewer_count = 0` yields `TIGHT` and `pending_replenishment_kegs_total = 2`. Expectations corrected, with the two governing PRD sentences quoted.
- `test_corner_state_machines.py::test_replaying_a_release_is_refused_and_does_not_re_sign_the_certificate` — expected `ERR_ALREADY_TERMINAL`; ladder step 11's enumerated terminal-dimension list contains no cycle stage, and step 10 explicitly names cycle `stage` for release ⇒ `ERR_INVALID_STATE` (409). No assertion weakened — the `error_id` check remains exact.

**Fixes to `implementation/`:**
- `util.py` + `response.py` + `routes/parties.py` — **root cause of ~37 of the 49 iteration-1 failures.** Every instant was rendered with three fractional digits. PRD scopes "three fractional digits" only to `created_at`/`updated_at` and `api_request_timestamp`, and renders the logical clock verbatim as `2026-08-01T00:00:00Z`. Added `util.iso_instant()`, made `response._clean` field-aware, and switched the clock endpoint's `current_utc`/`previous_utc` to the instant format. (All 3 `.000Z` occurrences in the test tree are request *inputs*, never expectations.)
- `util.py` + `response.py` + `routes/pools.py` — iteration 2's single residual failure. `last_pressure_test_at == created_at` on a defaulted import broke once the two fields rendered differently, yet both PRD sentences are verbatim binding. Added a `util.MillisInstant` datetime marker so a value *copied from* `created_at` serializes exactly like its source, while a supplied or cycle-derived `last_pressure_test_at` keeps the instant format.
- `routes/recovery.py::chargeback_resolution` — removed the `ERR_ALREADY_TERMINAL` pre-check on a non-`ISSUED` chargeback. Ladder step 11's terminal-dimension list is *enumerated* and does not include `chargeback_status`, so step 10 owns it ⇒ `ERR_INVALID_STATE`. (This contradicts the worklog's blanket "terminal before invalid-state" resolution, which is wrong for this dimension.)
- `routes/floats.py::read_agreement` — a foreign brewer read another brewer's agreement and got 200. Ladder step 8 plus the §4 endpoint table require `ERR_NOT_RESOURCE_OWNER`; added `middleware.owner_check`, scoped narrowly to this route.

No endpoint, field, side effect, or header was added without a verbatim PRD sentence; no data is seeded at startup; storage remains in-memory dicts only (`db.py`), verified free of SQLite, file writes, and `/tmp` caches, so `start.sh` re-invocation under per-test-server isolation wipes all state.

### Orchestrator independent verification (2026-09-03T18:00Z)

The subagent's final sweep left no `results.*.json` on disk (a known failure mode of this step), so the orchestrator re-ran the full 8-round `setsid nohup` sweep itself. Result: **all 8 rounds 200/200**, written to `workspace/implementation/results.{1..8}.json` (sweep log at `workspace/sweep_verify.log`). Also independently audited: `test_suite/` holds 200 test functions across 19 test files + conftest, **0** `pytest.mark.skip` / `xfail` markers anywhere in `test_suite/` or `test_helpers/`, and **0** matches for `sqlite` / file-write / `/tmp` in `implementation/`. Step 7's green claim is confirmed.

## Step 8: Finalize PRD — 2026-09-03T17:47:00.000Z

`PRD_FINALIZED.md` written. **PRD.md 561 lines → PRD_FINALIZED.md 563 lines (+2 lines, +0.36%)**; 5 paragraphs touched, 4 revised in place plus 1 inserted paragraph.

### Changes

- **§2.4 (Resource Identity, Timestamps and Version Counters)** — *insert* — new paragraph pinning instant serialization: only `created_at`, `updated_at` and `api_request_timestamp` carry three fractional digits; every other returned instant renders to whole seconds (`2026-08-01T00:00:00Z`) when its millisecond component is zero and with exactly three fractional digits otherwise, supplied instants held at ms resolution; plus the single exception that a `last_pressure_test_at` defaulted from the keg's own `created_at` renders like its source — `implementation/util.py:27-72` (`iso`/`iso_instant`/`MillisInstant`), `implementation/response.py:36-52` (`_MILLIS_FIELDS`, `_clean`), `implementation/routes/pools.py:119`, `implementation/routes/parties.py:216-217`.
- **§2.1 (RBAC)** — *revise* — added "the `brewer_id` of a float agreement being read on its own path" to the brewer-side ownership enumeration, and a negative clause that no other brewer-side read is ownership-checked — `implementation/routes/floats.py:138-149`, `implementation/middleware.py:71-78`.
- **§3.3 (Float Agreements)** — *revise* — the individual agreement read is ownership-checked (`ERR_NOT_RESOURCE_OWNER` after resolution); the list endpoint is not — `implementation/routes/floats.py:148` vs `:152-163`.
- **§3.6 (return scan)** — *revise* — `current_distributor_id` is deliberately left in place at return; a service release is the only operation that clears it — `implementation/routes/scans.py:229-231` vs `implementation/routes/service.py:275`.
- **§3.7 (`AGREE`)** — *revise* — the `RECONCILIATION_OFFSET` accrual's remaining fields: `keg_id` copied from the claim, `dwell_days`/`tier_pct_bp`/`cooperation_multiplier_bp` all `0` (not unset), `triggering_scanned_at`/`paid_at`/`clawback_reason` unset — `implementation/routes/recovery.py:414-428`.

### No-edit findings (PRD already determines the behavior)

- `chargeback-resolution` on a non-`ISSUED` row → `ERR_INVALID_STATE`: ladder step 11's terminal-dimension list is enumerated and excludes `chargeback_status`, while step 10 names it. The impl fix aligned code *to* PRD.
- Release replay → `ERR_INVALID_STATE`: same ladder reasoning for cycle `stage`.
- All five `test_suite/` corrections (validations fixture, dual-variant clock pin, `fill_count` deltas, sweep `TIGHT`/`pending_replenishment_kegs_total=2`, release-replay error id) were fixture/expectation bugs against PRD-determined rules.

### Per-edit pre-edit search log

1. **§2.4 instant rendering.** (a) Subject: serialization of every datetime-valued response field. (b) Enumerated: `grep -rn "MillisInstant\|iso_instant\|util.iso("` across all of `implementation/`; read `response._clean` (only key-based branch is `created_at`/`updated_at`; lists/dicts recurse), `util.iso`, `util.iso_instant`, `util.parse_instant` (ms truncation), `clock.py` (`DEFAULT_UTC` microsecond 0), and every route's row literals for datetime fields — scans (`scanned_at`, `recorded_at`), kegs (4 instants), orders (`dispatched_at`), cycles (`received_at`/`cleaned_at`/`inspected_at`/`pressure_tested_at`/`released_at`), claims (`evidence_scanned_at`, `closed_at`), accruals (`triggering_scanned_at`, `paid_at`), investigations (`hold_started_at`, `closed_at`), `calc.loss_rate` window bounds, clock endpoint. (c) Adjustment: wrote "instant" throughout rather than "timestamp" so the `date`-valued fields (`effective_date`, `cooperation_effective_date`) rendered by `date.isoformat()` are untouched; dropped a planned "dates render as YYYY-MM-DD" sentence as out of scope; scoped the `MillisInstant` exception to the *defaulted-at-import* case only, since release-set and caller-supplied values are plain datetimes.
2. **§2.1 ownership enumeration.** (a) Subject: which operations run step-8 ownership. (b) Enumerated: `grep -rn "owner_check\|ERR_NOT_RESOURCE_OWNER"` → `floats.py:148`, `recovery.py:123/359/480`, `scans.py:74/76`; then read *every* GET whose role list includes Brewer/Distributor and confirmed no check on `/brewers/{id}`, `/brewers/{id}/loss-rate`, `/distributors/{id}`, `/pools/{id}`, `/kegs`, `/kegs/{id}`, `/kegs/{id}/dwell`, `/scan-events*`, `/float-agreements` (list), `/issuance-orders*`, `/loss-assessments*`, `/reconciliation-claims*`, `/return-incentives` (list). (c) Adjustment: narrowed to "being read on its own path" so the agreement *list* is excluded, and scoped the negative clause to "brewer-side" so it cannot be read as contradicting the PRD's existing distributor-side accrual-read check.
3. **§3.3 agreement read.** (a) Subject: `GET /float-agreements/{id}` vs `GET /float-agreements`. (b) Enumerated: `floats.read_agreement` (404 before owner check) and `floats.list_agreements` (no actor captured at all). (c) Adjustment: added "once the agreement has been resolved" to keep `ERR_AGREEMENT_NOT_FOUND` ahead of the 403, and an explicit exemption for the list endpoint.
4. **§3.6 `current_distributor_id`.** (a) Subject: every write to `current_distributor_id`. (b) Enumerated: `grep -rn "current_distributor_id"` → `pools.py:131` (import default null), `pools.py:176` (list filter), `scans.py:145` (return-scan party equality), `scans.py:219` (distribution sets it), `service.py:275` (release clears it); checked order cancel (`floats.py:331-340`, clears only brewer-side), theft hold/resume/close (`recovery.py:631-698`, never touches it). (c) Adjustment: phrased as "a service release is the only operation that clears that field" rather than "it is cleared at the next service release", since a keg may be scrapped or written off from `IN_SERVICE` and never have the field cleared.
5. **§3.7 offset-accrual defaults.** (a) Subject: the `ReturnIncentiveAccrual` row shape at both mint sites. (b) Enumerated: `recovery.py:414-428` (offset mint) against `scans.py:254-268` (`RETURN_DWELL` mint), plus every later writer of those fields — `pay_accrual` (`recovery.py:516-517`, sets `status`/`paid_at`) and the write-off clawback (`recovery.py:680-682`, sets `status`/`clawback_reason`) — and the ledger/stat recomputes that filter on `accrual_type`. (c) Adjustment: used "open unset" rather than "are unset" for `paid_at`/`clawback_reason` so a later payment or clawback on an offset accrual is not contradicted, and confined the whole clause to the `RECONCILIATION_OFFSET` sentence so §3.6's `RETURN_DWELL` field semantics stay verbatim.

### Orchestrator verification

`diff PRD.md PRD_FINALIZED.md` reports exactly **5 change hunks / 10 changed lines** — a genuinely minimal patch, not a rewrite. `PRD_FINALIZED.md` still carries all 5 `##` section headings and ends on the final complete error-table row, so it is not truncated.

## Step 9: Complete PRD — 2026-09-03T18:40:00.000Z

Orchestrator note on method: Step 9 was deliberately run as **three sequential, file-partitioned passes** over `implementation/` rather than one scan, because a single subagent asked to scan a 3479-line implementation against a 563-line PRD tends to no-op (producing a `PRD_COMPLETED.md` byte-identical to its source). Partition: pass A = `app.py`, `clock.py`, `db.py`, `errors.py`, `response.py`, `util.py`, `middleware.py`, `services/*.py`; pass B = `routes/parties.py`, `routes/pools.py`, `routes/floats.py`; pass C = `routes/scans.py`, `routes/service.py`, `routes/recovery.py`. Pass A created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; B and C edited it in place. Each pass received the previous passes' "already uniquely pinned / do not re-litigate" list so the passes did not contend, and passes B and C were explicitly asked to check whether the earlier passes' wording had over-claimed — which caught two real over-broad statements (see below).

### Pass A — core + services (9 ambiguity-pins, 0 mismatch-revisions)

`PRD_FINALIZED.md` 563 lines / 127,784 chars → 563 lines / 129,847 chars. `errors.py`'s HTTP map and the §5 table were verified programmatically to agree on all 67 codes; every constant and formula in `services/calc.py` / `services/recompute.py` was already uniquely pinned and the PRD's worked examples reproduce exactly.

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric characters — `response.py:20-24`
- §2.3 — insert — ambiguity — explicit `+` counts as non-integer for `limit`/`offset`; whitespace ignored; an empty query parameter is treated as absent; boolean list filters accept `true`/`false`/`1`/`0` in any case, else `ERR_INVALID_REQUEST` 400 — `middleware.py:47-68, 81-97`
- §2.3 — insert — ambiguity — the `created_at` sort is stable, so rows tying on `created_at` come back in creation order — `services/view.py:122-125`
- §2.4 — insert — ambiguity — `updated_at` is set equal to `created_at` at creation — `util.py:187-192`
- §2.5 — insert — ambiguity — `Z` or any numeric offset accepted and normalised to UTC, a zone-less instant read as UTC, sub-millisecond precision truncated not rounded — `util.py:75-87, 71-72`
- §2.7 — insert — ambiguity — rejection of an invented version field is `ERR_INVALID_REQUEST` 400; each guarded operation accepts only its own field — `util.py:209-221`
- §2.8 step 4 — insert — ambiguity — an integer field is never satisfied by a JSON boolean; string fields rejected when empty/whitespace-only or outside declared length bounds — `util.py:245-282`
- §3.6 — insert — ambiguity — `limit_days` and `approaching_days` both read 0 for a custody state with no dwell limit — `services/calc.py:114-129`
- §5 preamble — insert — ambiguity — an undeclared path returns `ERR_INVALID_REQUEST` under 404 and an undeclared method under 405, trailing slash insignificant; all other `ERR_INVALID_REQUEST` occurrences are 400 — `app.py:17, 29-37`

Judged already pinned but borderline (handed forward): `elapsed_days` floor division vs §2.5 "discarding the remainder" (differ only for negative spans, all negative-reachable paths clamp or compare against a positive threshold); `has_more = (offset + len(rows)) < total_count`; `not_future_*` strict `>` so an instant equal to the clock is accepted; `apply_changes` with an empty change set never bumps.

### Pass B — parties / pools / floats (11 ambiguity-pins, 3 mismatch-revisions)

129,847 → 132,269 chars (+2,422), 563 lines unchanged. 14 changes across 13 lines.

- §2.8 ¶2 — revise — mismatch — PRD claimed the path pool "is resolved before the request body is examined at all"; every route parses and validates body and pagination *before* resolving path ids, matching the ladder's own step 4/5 < step 6 — `routes/pools.py:95-110, 156-159`
- §2.8 step 11 — revise — mismatch — the ladder's 10-before-11 order would make `ERR_ALREADY_TERMINAL` unreachable for orders; scoped clause added for the three order transitions and agreement activation only — `routes/floats.py:241-245, 296-300, 327-330, 94-97`
- §2.7 — revise — mismatch — **corrected pass A's over-broad wording**: A's blanket "operations not named here must reject an invented version field" is false for the replenishment sweep, the one POST that reads no body. Rescoped to "operations that read a request body" — `routes/pools.py:226-231`
- §2.3 — insert — ambiguity — non-boolean list filters are plain equality with no domain validation: an out-of-enum value or unknown id yields an empty page, not 400/404 — `routes/pools.py:160-165, 176-180`, `routes/floats.py:156-158, 364-365`
- §3.6 — insert — ambiguity — the sweep examines no body, so anything sent in one is ignored rather than rejected — `routes/pools.py:226-231`
- §3.6 — insert — ambiguity — `tight_agreement_ids`/`suspended_agreement_ids` are in ascending `created_at` order; `pending_replenishment_kegs_total` sums across every `ACTIVE` agreement (`HEALTHY` ones contributing 0) — `routes/pools.py:258-263`
- §4 `GET /commodity-index` — revise — ambiguity — "in effective-date order" pinned to ascending, overriding the default `created_at` order — `routes/parties.py:199-200`
- §3.9 — insert — ambiguity — a `basis` other than `TRAILING_90D`/`LIFETIME` is refused with `ERR_INVALID_REQUEST` *before* the path brewer is resolved; the reported `upheld_loss_count`/`fill_count` are the numerator and denominator of the requested basis — `routes/parties.py:70-86`
- §3.1 — insert — ambiguity — `status_reason` on a brewer-status override is 1–500 chars, and omitting it *clears* any stored reason — `routes/parties.py:95, 100`
- §3.3 — insert — ambiguity — activating a non-`DRAFT` agreement: `ACTIVE` → `ERR_INVALID_STATE`, `TERMINATED` → `ERR_ALREADY_TERMINAL` — `routes/floats.py:94-97`
- §3.3 — insert — ambiguity — `terminated_reason` is 1–500 characters — `routes/floats.py:118`
- §3.4 — insert — ambiguity — `cancel_reason` is 1–500 characters — `routes/floats.py:323`
- §3.2 — insert — ambiguity — `fill_count` and `fills_at_last_pressure_test` both default to 0 and may not be negative — `routes/pools.py:100-102`
- §2.4 — insert — ambiguity — the no-op rule is confined to cascade recomputes: a direct write re-stating an identical value still bumps `version` and `updated_at` — `routes/parties.py:101, 166`

Judged already pinned but borderline (handed forward): ladder positions in `create_order` (12→13→14→16→43→50) and `allocate` (9→11→10→12→13/14→15→16→45→46→50) reproduce §2.8 exactly, including the deliberate `>` on order-creation credit vs `>=` on allocation; no ownership check on keg/order/pool/party reads or any list; `effective_date` on a cooperation agreement or index posting and `last_pressure_test_at` on an import are not future-checked; a direct set of tier `SILVER`/`GOLD` is accepted; all role lists match §4.

### Pass C — scans / service / recovery (14 ambiguity-pins, 11 mismatch-revisions)

132,342 → 142,708 chars (+10,366), 563 lines unchanged — every edit an in-paragraph insert or revision.

- §2.5 / §2.8 step 33 — revise — mismatch — added the `occurred_at` of a recorded service step to the future-check enumeration — `service.py:187`
- §2.8 step 4 — insert — ambiguity — JSON `null` counts as absent (required→missing, optional→default, conditionally forbidden→not an error); sole exception the three §2.7 version fields, rejected on mere presence — `util.py:233,248,270,339` vs `util.py:219`
- §2.8 step 11 — revise — mismatch — **corrected pass B's scoping**: terminal-beats-state rescoped to "same dimension of the same row" (order allocate/dispatch/cancel, agreement activation, assessment dispute *and* resolve, claim response, investigation status change), preserving B's two counterexamples as different-dimension cases, plus the late keg-terminal clause on claim `AGREE` — `floats.py:96-99`, `recovery.py:145,365,619`, `scans.py:85-94`, `service.py:94`
- §2.8 step 24 — revise — mismatch — only `INSPECTION_MAJOR_DEFECT` is BLOCKED; `PRESSURE_TEST_FAIL` is retestable and refused a release by step 10; blocked-before-stage on release, blocked-after-23 on a step — `service.py:183-186, 246-256`
- §2.8 step 32 — revise — ambiguity — `ERR_NO_CHARGEABLE_PARTY` precedes `ERR_NO_COMMODITY_INDEX` — `recovery.py:72-78`
- §3.3 — revise — mismatch — `float_posture` recompute fires on every pool-census recomputation, not only on a posture change; the §2.4 no-op rule makes it invisible — `recompute.py:145-150`
- §3.5 — insert — ambiguity — `retail_account_code` is 1–120 characters, no format constraint — `scans.py:61-62`
- §3.5 — insert — mismatch — the three counterparty gates run only when `brewer_id` resolves and equals `current_brewer_id`; otherwise silence then `ERR_SCAN_PARTY_MISMATCH`; the collar check reads the *supplied* brewer, so `ERR_BRAND_MISMATCH` can pre-empt the party mismatch — `scans.py:97-106, 128-130`
- §3.6 — revise — mismatch — the sweep is the only writer of `APPROACHING`/`OVERDUE`; import, allocation, cancellation, release, evidence hold and write-offs only force `WITHIN_LIMIT`; resume, `RECOVERED` close and every scan leave it alone — `floats.py:272,339`, `service.py:279`, `recovery.py:175,636,664`, `pools.py:126`
- §3.6 — insert — ambiguity — accrual payment judges `ERR_DISTRIBUTOR_SUSPENDED` before `ERR_ACCRUAL_NOT_PAYABLE`; `paid_at` is not future-checked — `recovery.py:509-515`
- §3.6 — revise — mismatch — "only operation that writes `dwell_flag`" narrowed to "only writer of `APPROACHING`/`OVERDUE`" — `pools.py:239-243`
- §3.7 — insert — ambiguity — the three who-may-move rules are concerns, not judgement order: ownership → staleness → terminality → who-may-move (`ERR_INVALID_STATE`) → turn-taking — `recovery.py:359-384`
- §3.7 — insert — ambiguity — a written-off keg on `AGREE` is `ERR_ALREADY_TERMINAL` (409), judged after turn-taking — `recovery.py:390-393`
- §3.8 — insert — ambiguity — centre `name` 1–120; `region_code` exactly two uppercase letters — `service.py:45-47`
- §3.8 — insert — ambiguity — every step's `occurred_at` is future-checked; the CLEAN/INSPECT ordering constraints are `ERR_INVALID_REQUEST` judged last; `PRESSURE_TEST` has no ordering constraint — `service.py:187-192`
- §3.8 — insert — ambiguity — a pressure FAIL still records `pressure_tested_at`, leaves the certifier unset, moves the keg to `QUARANTINED`; a first `PASS` touches the keg not at all — `service.py:211-231`
- §3.8 — insert+revise — mismatch — a passing retest moves custody only, `service_state` stays `SERVICE_FAILED` until release; a `PRESSURE_TEST_FAIL` cycle's release is `ERR_INVALID_STATE` — `service.py:219-222, 246-256`
- §3.8 — insert — ambiguity — `released_at` is recorded as given, not future-checked and not ordered against earlier cycle timestamps — `service.py:241`
- §3.9 — insert — ambiguity — assessment creation always bumps the keg's `version`, so a superseding create must quote the bumped value — `recovery.py:109-110`
- §3.9 — insert — ambiguity — `amount_cents` on a `REVERSE` is shape-checked (≥ 0) then ignored, and may be omitted — `recovery.py:195-197`
- §3.10 — revise — mismatch — the "attached kegs may sit in different pools" clause replaced: every attached keg is of the investigation's own pool; a missing index is tolerated (exposure 0, `commodity_index_id` unset); empty `keg_ids` accepted — `recovery.py:533-545, 556-570`
- §3.10 — insert — ambiguity — `outcome_notes` on a hold or resume is shape-checked then ignored; only a close records it — `recovery.py:606, 690-692`
- §3.10 — insert — ambiguity — a hold's `keg_ids` are resolved pool-unscoped (`ERR_KEG_NOT_FOUND` vs `ERR_KEG_NOT_ATTACHED`); an empty hold list is accepted — `recovery.py:609-613, 628-637`
- §3.10 — insert — ambiguity — kegs written off as `STOLEN` stay attached (still counted in `attached_keg_count`/exposure, `held_keg_count` → 0); `clawback_reason` is the fixed `THEFT_INVESTIGATION_WRITTEN_OFF` — `recovery.py:655-664, 683-685`

Pass C's closing judgement: its partition is exhausted — every endpoint, validation bound, ladder position, transition, cascade, default, ignored field and response field in `scans.py`/`service.py`/`recovery.py` is now either already pinned by the PRD or pinned by this pass, each wording cross-checked against non-partition callsites before committing. Residual items left open are the handoff list (decided by earlier passes, not re-litigated) and one presentational note: §3.9's narrative lists the already-open rule before step 32 while the ladder puts step 32 first; the implementation follows the ladder, and §2.8's opening paragraph already declares the ladder authoritative, so nothing needed pinning.

### Orchestrator final verification

- `PRD_COMPLETED.md`: **563 lines**, 142,708 bytes. **Not** byte-identical to `PRD_FINALIZED.md` (the no-op failure mode did not occur): `diff` reports **84 changed lines**, versus 10 for `PRD_FINALIZED.md` against `PRD.md`.
- Structural integrity intact: all 5 `## ` headings, §4 table still 58 rows (header + separator + 56 endpoints), §5 table still all 67 `ERR_*` rows, last line the complete final error row. Line count unchanged from `PRD_FINALIZED.md`, confirming every edit was an in-paragraph insert/revision with no new sections.
- Regression: no `.py` file under `implementation/`, `test_suite/` or `test_helpers/` has an mtime newer than the orchestrator's green sweep, so the verified **8/8 rounds at 200/200** still describes the delivered code. `results.{1..8}.json` from that sweep are in place under `workspace/implementation/`.

**Pipeline complete.** All nine steps executed; `workspace/PRD_COMPLETED.md` is written.
