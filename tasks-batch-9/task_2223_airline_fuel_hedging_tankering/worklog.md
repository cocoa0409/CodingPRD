# Worklog — task_2223_airline_fuel_hedging_tankering

## Step 1: Create task directory — 2026-09-01T07:01:30.000Z

Created `tasks/task_2223_airline_fuel_hedging_tankering/` and `tasks/task_2223_airline_fuel_hedging_tankering/workspace/` (task directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T08:40:00.000Z

All three artifacts are complete and the linter passes.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2223_airline_fuel_hedging_tankering/`):
- `SCAFFOLD.yaml` (2798 lines) — §1.0–§1.7 only; contains neither design key
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2178 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2414 lines) — single key `scaffold_corner_design`

**Lint verdict (verbatim, `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2223_airline_fuel_hedging_tankering`):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2223_airline_fuel_hedging_tankering/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2223_airline_fuel_hedging_tankering/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2223_airline_fuel_hedging_tankering/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     13
  §1.8 instances scanned:     26
  §1.9 instances scanned:     37
  Calls scanned (§1.8+§1.9):  722

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Entities: 13 (HedgePolicy, Counterparty, Station, SupplyContract, ConsumptionForecast, HedgeProgram, HedgeInstrument, EffectivenessTest, CollateralPosting, MarkToMarketRun, FlightLeg, TankeringDirective, PolicyException); EffectivenessTest is the only `common_fields: false` row
- State machines: 7 (ConsumptionForecast, HedgeProgram, HedgeInstrument two-dimensional trade+accounting, CollateralPosting, MarkToMarketRun, TankeringDirective with revision cycle + supersession, PolicyException) plus 3 §1.2.1 OCC rules
- Calculations: 11; Validations: 27 ordered rows; Endpoints: 57; Errors: 50; Roles: 6
- Difficulty design: 9 rule blocks / 26 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- Corner design: 9 sections / 56 instances = 37 with full `test_recipe` + 19 `excluded_because` stubs — entities 9 (9/0), state_machines 10 (5/5), calculations 7 (3/4), validations 11 (5/6), endpoints 4 (4/0), errors 3 (3/0), rbac 4 (4/0), cross_cutting_complexity_layers 7 (3/4), consistency_model 1 (1/0)

**Verified invariants:** every one of the 50 error codes is triggered by at least one §1.8/§1.9 recipe; all 57 endpoints are exercised; every stub's `excluded_because.difficulty_instance` resolves to a real §1.8 instance; instance names unique across both design files; no forbidden concurrency vocabulary; all fixture literals recomputed under Decimal/ROUND_HALF_UP. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-01T08:40:30.000Z

Copied `INSTRUCTION.md` → `tasks/task_2223_airline_fuel_hedging_tankering/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T08:53:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2223_airline_fuel_hedging_tankering/workspace/PRD.md` (404 lines). `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were never opened.

**Section list**

- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-identical to the skill's canonical block, verified programmatically); 2.3 Pagination and List Filtering; 2.4 Resource Identity, Audit Stamps and the Logical Clock; 2.5 Validation Precedence; 2.6 Version Pinning on Parented Creates; 2.7 Rounding Discipline; 2.8 Ledger Integrity, Cascades and Compensating Reversals; 2.9 The Governing Policy
- §3 Business Logic & Workflows — 3.1 Reference Data: Hedging Policy and Counterparty Credit Standing; 3.2 Stations, Supply Contracts and the Inventory Ledger; 3.3 From Consumption Forecast to Activated Hedge Programme; 3.4 The Instrument Book: Proposal, Execution and Termination; 3.5 Margin Calls, Collateral Posting and Collateral Return; 3.6 Hedge Accounting: Designation, Effectiveness Testing and De-designation; 3.7 The Monthly Mark-to-Market Run; 3.8 Tankering: Flight Legs, Directives and Reconciliation; 3.9 Policy Exceptions: The Governed Override Channel
- §4 API Endpoints Summary — 57 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- §5 Error Codes Summary — 50 rows, 2 columns (Error ID, HTTP Status Code)

Document ends at §5; no audit footer inside the file.

**Field coverage check:**
- entities[].fields: 142 required, 142 present, 0 missing
- endpoints[].request_body: 94 required, 94 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing (the scaffold carries no separate `query_params` key; the 20 filter names plus `limit`/`offset` live in `input` and are all covered in §2.3)
- Status: PASS

**Rule coverage check:**
- validations[] with priority: 27 checked, 27 expressed in prose, 0 missing (the §2.5 ladder is emitted as an ordered 1–27 list; every alternate `error_id` in each compound entry verified against its own numbered item)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + `expected_<parent>_version` + `ERR_STALE_VERSION`/412 all named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed, 0 missing (includes both independent `HedgeInstrument` dimensions, the two system-event transitions, and both self-loops)
- calculations[]: 11 checked, 11 fully expressed, 0 missing; every numeric constant in the scaffold's calculation blocks verified present in the prose
- validations[] conditions: 27 checked, 27 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 57 endpoints checked, all side-effect clauses expressed, 0 missing (includes the two version-exempt GET recomputations and the logical-clock endpoint)
- entities[].fields[] structured content: 142 checked, 142 reconstructible from prose, 0 missing; all enum members and all field constraint bounds verified present
- sibling-branch symmetry: 12 groups checked (3 instrument types × strike validation / delta / margin rate / MTM formula, 4 credit-posture tiers, 4 margin add-on tiers, 3 supply-posture tiers, 4 season factors, 3 fleet burn factors, exception approve/deny, posting post/return, planned/reconciled tankering bases, terminate-from-PROPOSED vs terminate-from-EXECUTED), 12 with equal prose density, 0 asymmetric
- Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 864
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS

Two repairs were made during the audit: §2.5 item 5 originally said "the corresponding 404 from the same family" and now names all six body-FK error IDs explicitly, and the margin add-on tiers now state 0.00/0.10/0.25/0.50 as numerals rather than in words. Both re-verified on a second full pass.

## Step 6: Generate implementation — 2026-09-01T09:22:00.000Z

Implementation is complete and verified end-to-end.

### Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2223_airline_fuel_hedging_tankering/workspace/implementation/`:

- **Entrypoint / launcher:** `app.py`, `start.sh` (executable), `requirements.txt` (`flask>=3.0`)
- **Foundation:** `db.py` (in-memory `Store` + logical clock), `errors.py` (all 50 error IDs -> HTTP codes), `response.py` (envelope), `middleware.py` (auth ladder steps 1-2, `new_row`, `touch` version accounting), `validators.py` (body/query coercion, pagination), `calc.py` (all Decimal formulas + constants), `domain.py` (derived aggregates + cascades), `serializers.py` (derived-field projection), `fetch.py` (404 resolution)
- **Routes (12 blueprints):** `routes/policies.py`, `counterparties.py`, `stations.py`, `forecasts.py`, `programs.py`, `instruments.py`, `postings.py`, `mtm.py`, `legs.py`, `directives.py`, `exceptions.py`, `clock.py`

### Endpoint count
**57 routes registered** — 56 under `/fuel/...` plus `POST /_clock/set_current_utc`, matching the PRD §4 table exactly.

### start.sh
Reads `$PORT` (default 8000), `app.run(host="0.0.0.0", port=port, threaded=False, use_reloader=False)`, and runs in the **foreground** via `exec` (no `&`, no nohup). Verified live: `PORT=8123 ./start.sh` came up in under 3 s and `ss -ltn` showed `LISTEN 0.0.0.0:8123`.

### Storage
In-memory dicts only. `grep` for `sqlite|open(|json.dump|pickle|shelve` across the package returns nothing — no disk persistence, and the 13 entity dicts are empty at import time (nothing seeded, preloaded or hardcoded).

### Runtime verification
A 60-call smoke pass through the Flask test client exercised the full lifecycle and finished with **"ALL SMOKE EXPECTATIONS MET"** (every asserted status code matched):
- Clock set -> echoed verbatim; all stamps derived from it (`2026-08-10T12:00:00.000Z`), never wall-clock.
- Policy -> counterparty -> stations -> supply contracts (incl. `ERR_CONTRACT_TERM_OVERLAP`, `ERR_CONTRACT_BUFFER_VIOLATION`, `ERR_DUPLICATE_STATION_CODE`) -> inventory adjustment flipping `supply_posture` SHORT->NORMAL and `days_cover` 1.0->7.0.
- Forecast publish -> program size (`consumption_basis_gallons` 1 100 000 from the 1.10 SUMMER factor) -> SWAP + COLLAR proposals (incl. `ERR_STALE_VERSION` 412) -> submit -> SoD-blocked activate (403) -> activate -> execute (margin 24 000, counterparty ledger 0.48 % NORMAL) -> designate.
- Collateral: `ERR_COLLATERAL_SHORTFALL` 422, post, return-after-settlement.
- Effectiveness tests: PASS then cumulative 5.4545 FAIL -> auto de-designation. Test rows carry only `id`/`created_at` (no `version`/`updated_at`), as required.
- MTM run: duplicate period 409, compute (1 instrument, 160 000 undesignated), publish -> programme posture BREACH -> one `SYSTEM_BREACH` / `EARNINGS_VOLATILITY_BREACH` exception with `hedge_instrument_id: null`, plus settlement of the matured trade.
- Tankering: leg (`uplift_cap_gallons` 2985.07) -> directive (penalty 300.0 gal, net +3305.00) -> approve with pinned prices/contract ref -> execute (inventory debit) -> reconcile (variance -354.35, inventory true-up).
- Exceptions: `open_exception_count` on the governing policy moved 2->1 on approval; self-approval blocked with `ERR_SEGREGATION_OF_DUTIES`.
- Auth: missing headers 401, unknown role 401 `ERR_UNAUTHENTICATED`, wrong role 403 `ERR_FORBIDDEN_ROLE`, unknown id 404, `limit=101` 400. Error envelopes carry `response_type: "error"` with `data.{error_id,message}` and a `meta` limited to `api_request_id`/`api_request_timestamp`.

The one negative result during smoke testing was my own fixture, not a defect: the first directive scenario was genuinely uneconomic (payload ratio 1.41 -> 2.12x burn-penalty multiplier), so the server correctly returned `ERR_TANKERING_NOT_ECONOMIC`; re-running with an economic leg passed.

## Step 5: Generate unit tests — 2026-09-01T10:34:00.000Z

(Note: this agent was interrupted once by a transient API server error and was resumed with its context intact; the summary below is from the completed run.)

Generation and the Stage 2 self-audit are both complete and clean.

### Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2223_airline_fuel_hedging_tankering/test_helpers/` (9 modules): `__init__.py` (re-exports the pip-installed `prd_bench_local_runner.testing` primitives plus everything below), `api_client.py` (57-endpoint client), `api_errors.py` (all 50 error IDs), `constants.py`, `types.py`, `test_users.py` (role headers + fixed user IDs for SoD), `factories.py` (payload builders), `fixtures.py` (scenario builders `setup_sized_program` … `setup_proposed_directive`), `assertions.py` (tolerance wrappers `assert_money/assert_pct/assert_price/assert_ratio/assert_gallon_tenths/assert_whole_gallons` and ledger-group asserters).

`/home/ubuntu/github/CodingPRD/tasks/task_2223_airline_fuel_hedging_tankering/test_suite/` — `conftest.py` plus 17 test files:

- Queue B (breadth, §1.9): `test_01_reference_data_and_entity_defaults.py`, `test_02_state_machines.py`, `test_03_sizing_and_forecast_basis.py`, `test_04_validation_gates.py`, `test_05_endpoint_behaviour.py`, `test_06_error_catalogue.py`, `test_07_rbac.py`, `test_08_version_pinning_and_ledger_visibility.py`
- Queue A (depth, §1.8): `test_10_dual_variant_calculations.py`, `test_11_combinatorial_formulas.py`, `test_12_state_machine_cycles.py`, `test_13_cascades.py`, `test_14_validation_precedence.py`, `test_15_boundaries.py`, `test_16_cross_entity_state_gates.py`, `test_17_temporal_overlap.py`, `test_18_compensating_invariants.py`

### Test count

**153 test functions, 174 collected pytest items.** The 21-item gap is fully accounted for by `@pytest.mark.parametrize` expansion — test_02 (+1), test_06 (9 functions -> 24 items), test_07 (9 -> 14) — and nothing outside this task's `test_suite/` is being collected. `python -m pytest test_suite --collect-only -q` succeeds.

### Instances translated vs skipped

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): **26 of 26 translated**, 0 stubs in the file. Every instance carries >=2 tests (most 3, four at 4).
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 56 instances, of which 19 are `excluded_because:` stubs. **37 of 37 non-stub instances translated**, >=1 test each.
- **Zero instances skipped.** Every non-stub instance passed the PRD-first two-condition filter (verbatim PRD coverage present, and the PRD uniquely derives the asserted outcome), so there are no gap reasons to report. No `skip`/`xfail`/placeholder markers exist anywhere in the suite.

### Stage 2 self-audit result: `problems: 0`

Checked mechanically over both design YAMLs and every test file: exactly one `Design:` line as the final line of every test docstring (no untagged, no dual-tagged); every tag resolves to a real non-stub instance in the correct pool; no test maps to a stub; no invented baseline/smoke/RBAC/listing/pagination tests outside the two indices; no skip/xfail markers; and every quoted PRD span of >=5 words survives a literal grep of whitespace-normalised `workspace/PRD.md`.

Three pre-existing citations were repaired during the audit because they used ellipses inside the quoted span and so could not survive a literal grep — two in `test_01_reference_data_and_entity_defaults.py` (replaced with the complete §2.5 request-shape sentence and the complete §3.3 forecast-enumeration sentence) and one in `test_02_state_machines.py` (replaced with the full §3.7 programme-reclassification sentence).

Supporting integrity checks all clean: `compile()` on every file; every name imported `from test_helpers` resolves (0 missing); every `fx.*`, `f.*` and `api.*` attribute used across the suite exists on `fixtures`/`factories`/`ApiClient` (0 bad attributes). Nothing under `workspace/implementation/` and no sibling task directory was read or written.

## Step 7: Run tests and iterate — 2026-09-01T11:12:00.000Z

All 174 tests pass in all 8 parallel rounds. Here is the summary.

### Iterations run
**2 iterations** (2 x 8-round parallel sweeps, 174 tests each).

- **Iteration 1**: 173/174 in all 8 rounds. One deterministic failure, identical in every round (`test_03_sizing_and_forecast_basis.py::TestBasisInputFiltering::test_publishing_the_held_back_draft_admits_it_on_a_re_size`, `Setup step failed with HTTP 409: ERR_FORECAST_PERIOD_OVERLAP`).
- **Iteration 2**: 174/174 in all 8 rounds (`passed == total` in every `results.${i}.json`, `i = 1..8`).

No flakiness surfaced across the 16 total round-executions — the suite contains no race/concurrency tests (`run_race`, `assert_race_outcome`, `assert_exactly_one_succeeds` are all unused), so the only failure was deterministic.

### Tests deleted
**None.** The single failure passed both STEP 1 sub-checks:

- **1a COVERAGE** — the asserted rule is verbatim in PRD §3.3: *"Re-sizing is the only route by which a forecast published after an earlier sizing run enters an already-sized programme."*
- **1b UNIQUE DERIVABILITY** — a re-size must pick up a newly-published qualifying forecast; no PRD-faithful reader could produce an implementation where it does not. No collapse pattern applied.

### Fixes applied to `test_helpers/`
**None.** The offending setup helper lived inline in the test file (a `@staticmethod` on the test class), not in `test_helpers/`.

### Fixes applied to test_suite/ (STEP 2 — test bug)
`test_suite/test_03_sizing_and_forecast_basis.py` — `TestBasisInputFiltering._four_decoys_and_one_qualifying_forecast`: the held-back `DRAFT` decoy was built as `NARROWBODY`/`DOMESTIC_SHORT` over `2027-01`->`2027-04`, which is exactly the interval of the already-`PUBLISHED` `NARROWBODY`/`DOMESTIC_SHORT` qualifying forecast. PRD §3.3 states *"no other `PUBLISHED` forecast with the same `fleet_type` and the same `route_group` may have a half-open month interval that intersects this one"*, so the PRD-faithful implementation correctly rejected the later publish with `ERR_FORECAST_PERIOD_OVERLAP` — a fixture bug, not an implementation bug. Moved the decoy to `route_group="DOMESTIC_LONG"` over `2027-01`->`2027-03`, which merely *touches* (does not intersect, the intervals being half-open) the pre-existing `2027-03`->`2027-06` `DOMESTIC_LONG` decoy.

The fix makes the test **more** faithful to PRD, and preserves both assertions unchanged: the sibling test's `4,400,000` basis (the draft is still excluded on `status` alone — its fleet, route group and window all qualify) and this test's `5,400,000` after publication (`WINTER` weight 1.00 x 1,000,000).

### Fixes applied to `implementation/`
**None.** The reference implementation was already PRD-faithful on every one of the 174 assertions; no implementation check was removed, weakened, or added.

### Orchestrator verification (independent of the Step 7 subagent)

The subagent left no `results.*.json` on disk, so the orchestrator re-ran the full 8-round parallel sweep itself. Result, read straight off the eight freshly written files:

```
results.1.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
results.2.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
results.3.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
results.4.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
results.5.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
results.6.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
results.7.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
results.8.json {'passed': 174, 'failed': 0, 'errors': 0, 'total': 174, 'skipped': 0}
```

## Step 8: Finalize PRD — 2026-09-01T11:22:00.000Z

`workspace/PRD_FINALIZED.md` created. It is byte-identical to `PRD.md` (same md5), because no PRD edit traces to the single Step 7 item.

### Line counts
- `PRD.md`: 404 lines
- `PRD_FINALIZED.md`: 404 lines
- delta = 0 lines, 0.00% delta (md5 identical: `b141f37f…`)

### Changes
None. Zero inserts, zero revisions.

### Why no edit was warranted

The Step 7 diff contains exactly one item: a fixture bug in `test_suite/test_03_sizing_and_forecast_basis.py::TestBasisInputFiltering._four_decoys_and_one_qualifying_forecast`, with explicitly **zero** implementation fixes, **zero** test deletions, and **zero** `test_helpers/` fixes. (Note: neither `test_suite/` nor `test_helpers/` is present in this workspace — only `INSTRUCTION.md`, `PRD.md`, `implementation/` — so the fixture was verified indirectly, against implementation behaviour.)

The two candidate silences the brief flagged for that item both turn out to be already uniquely pinned in PRD §3.3, verbatim matching the implementation:

1. **Half-open forecast-publication overlap semantics** — PRD §3.3: "enforced only against already-`PUBLISHED` siblings: no other `PUBLISHED` forecast with the same `fleet_type` *and* the same `route_group` may have a half-open month interval that intersects this one … two forecasts that merely touch … do not intersect and are both allowed." `implementation/routes/forecasts.py:82-94` implements exactly that: skip self and non-`PUBLISHED`, require both `fleet_type` and `route_group` equality, then the standard strict half-open test `row.start < other.end and other.start < row.end`. Ladder position also matches (§2.5 item 7 state gate `ERR_FORECAST_INVALID_STATE` at line 78-80 precedes item 11 overlap).
2. **The forecast-eligibility filter a re-size applies** — PRD §3.3's four conditions plus the containment rule ("the forecast's `period_end_month` to be no later than the month immediately after the programme's `period_end_month`") map one-to-one onto `routes/programs.py:114-129` (`window_end = month_after(program["period_end_month"])`, `validators.py:165-170`), and the filter is re-evaluated live from `db.forecasts` on every call, so PRD's "Re-sizing is the only route by which a forecast published after an earlier sizing run enters an already-sized programme" is satisfied without further pinning. Season weights / single terminal rounding at `routes/programs.py:135-139` with `calc.SEASON_FACTOR` (`calc.py:14-19`) and `calc.r0` match §3.3 and §2.7.

### Pre-edit search log

No edits were committed, so there is no per-edit log. For completeness, the mandatory enumeration performed for the two edits considered and then rejected:

**Candidate A — forecast-publication overlap semantics (§3.3, para 194).**
- (a) Subject: the month-interval intersection predicate and its `PUBLISHED`/fleet/route scoping on forecast publication.
- (b) Paths enumerated and read: `implementation/routes/forecasts.py` (`publish_forecast` overlap loop, `create_forecast`'s `end <= start` shape check, `list_forecasts` filters), `implementation/validators.py:139-145` (`get_month`, lexicographic `YYYY-MM` ordering which makes the string comparisons in the predicate correct), `validators.py:165-170` (`month_after`, the only other month-arithmetic helper), plus grep for every other consumer of `period_start_month`/`period_end_month` — `routes/programs.py` (sizing containment, `create_program` closed-window check, `create_instrument` maturity-in-window check) and `serializers.py`. No path is mis-described by the existing prose; the programme window is separately and correctly described as closed at both ends, so no widening was needed.
- (c) Wording adjustment: none — no edit made; existing prose is already an exact description of all enumerated paths.

**Candidate B — re-size forecast eligibility / basis recomputation (§3.3, para 198-200).**
- (a) Subject: which forecasts a sizing run (first run and re-run) admits, and what a re-run overwrites.
- (b) Paths enumerated and read: `routes/programs.py:100-142` (`size_program`: state gate, DRAFT-only policy-`ACTIVE` gate, four filters, `ERR_NO_FORECAST_BASIS`, sum, `r0`, `touch`), `domain.py:27-28` (`governing_policy` — bound policy, not `active_policy()`), `domain.py:19-24` (`active_policy`, the contrasting live-policy reader used only by `station_derived`/`leg_uplift_cap`), `domain.py:130-162` (`program_coverage`, the three percentages recomputed off the new basis on every serialization), `serializers.py` program serializer, and every other reader of `consumption_basis_gallons` (`routes/instruments.py` coverage-ceiling and concentration gates). All are consistent with the existing prose, including the §2.9 distinction between bound-policy and live-`ACTIVE`-policy limits.
- (c) Wording adjustment: none — no edit made.

Out-of-scope observation (deliberately **not** patched, since it does not trace to the Step 7 item): PRD §3.3 says a first sizing run "additionally requires that the programme's bound policy still be `ACTIVE`" without naming the error code; the implementation raises `ERR_PROGRAM_INVALID_STATE` (`routes/programs.py:110-112`). That is a genuine PRD silence, but the Step 7 failure exercised a `SIZING -> SIZING` re-run, which never reaches that branch, so HARD SCOPE excludes it.

## Step 9: Complete PRD — 2026-09-01T11:35:00.000Z

All 24 edits verified in place and rendering cleanly; the clock endpoint (`routes/clock.py:52`) confirms the §2.4 verbatim-echo pin, and `test_14_validation_precedence.py` confirms the §3.4/§3.8 precedence pins do not contradict any live assertion (its execute scenarios use `PROPOSED` trades, and its revision scenario expects `ERR_NO_ACTIVE_SUPPLY_CONTRACT` with no cap check — exactly the behaviour the §3.8 revision now pins).

### Deliverable

`workspace/PRD_COMPLETED.md`

| | lines | chars |
|---|---|---|
| PRD_FINALIZED.md (source) | 404 | 92,986 |
| PRD_COMPLETED.md | 404 | 97,740 |
| delta | 0 | **+4,754** |

No new sections, no new paragraphs, no line-count change — 22 lines revised in place (lines 103 and 216 took two edits each, line 250 took three).

**Counts: 18 ambiguity-pins, 6 mismatch-revisions (24 changes).**

### Per-change log

- §2.1 — insert — ambiguity — the `StationCoordinator` ownership test bites on the inventory adjustment alone; its reads of stations, contracts, legs and directives are not station-scoped — `middleware.py:96-112`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the §2.4 logical clock, not wall time — `response.py:14-20`
- §2.2 — insert — ambiguity — row-creating operations answer 201, every other success answers 200 — `response.py:29-37`
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit` and negative `offset` are `ERR_INVALID_REQUEST`; an empty string counts as absent — `validators.py:196-215`
- §2.3 — insert — ambiguity — malformed `maturity_month`/`departure_date` filters are `ERR_INVALID_REQUEST`, while identifier filters are compared literally and never existence-checked — `validators.py:218-243`
- §2.4 — revise — ambiguity — the clock response's `data` is a single `current_utc` echoing the caller's string verbatim — `routes/clock.py:48-52`
- §2.5 (step 3) — insert — ambiguity — enumerated the required-but-not-persisted free-text notes per transition — `routes/programs.py:196`, `routes/directives.py:88`
- §2.5 (step 3) — insert — ambiguity — body-less transitions accept an absent or empty body; a non-object body is `ERR_INVALID_REQUEST` — `validators.py:24-38`
- §2.7 — insert — ambiguity — input-scale limits: prices 4 dp, percentages/dollars/`min_days_cover` 2 dp, gallon/minute/pound inputs and `requested_limit_value` any scale — `validators.py:96-140`
- §2.9 — insert — ambiguity — when several policies are `ACTIVE`, the most recently created one governs — `domain.py:22-28`
- §3.2 — insert — ambiguity — `consortium_pool_gallons` must be >= 0 and is overwritten even at a non-member station; negative-inventory rejection is reported after the ownership check — `routes/stations.py:156-179`
- §3.3 — insert — ambiguity — the first sizing run's policy-still-`ACTIVE` gate answers `ERR_PROGRAM_INVALID_STATE` — `routes/programs.py:106-112`
- §3.3 — insert — ambiguity — the open-instrument requirement on submission answers `ERR_PROGRAM_INVALID_STATE` — `routes/programs.py:154-156`
- §3.4 — insert — ambiguity — a maturity outside the programme window is `ERR_INVALID_REQUEST`, raised after the path programme resolves but before `counterparty_id` is looked up — `routes/programs.py:284-289`
- §3.4 — revise — **mismatch** — the trade's own state check precedes every other execution gate (including `ERR_PROGRAM_NOT_ACTIVE`); removed the trailing duplicate sentence that implied otherwise — `routes/instruments.py:62-70`
- §3.4 — insert — ambiguity — termination reclassifies no programme MTM bucket and recomputes no posture — `routes/instruments.py:185-196`
- §3.5 — revise — **mismatch** — the posting row's own status is tested before the covered trade's; `amount_usd` is >= 0 at two decimals — `routes/postings.py:24-33`
- §3.6 — revise — **mismatch** — the already-`DESIGNATED` check precedes the trade-state and programme gates — `routes/instruments.py:131-142`
- §3.6 — insert — ambiguity — a zero cumulative item change yields `cumulative_ratio` 0.0000, which fails the band — `calc.py:238-252`
- §3.7 — insert — ambiguity — publish scope is re-derived at the publication instant and `instrument_count` is not restated — `routes/mtm.py:105`
- §3.7 — revise — **mismatch** — hop 3 refreshes and version-bumps every counterparty facing an in-scope instrument, not only those drawing a fresh margin call — `routes/mtm.py:144-145`
- §3.7 — revise — **mismatch** — the auto-raised breach exception leaves `hedge_instrument_id` null — `routes/mtm.py:171`, `domain.py:161-179`
- §3.8 — revise — **mismatch** — the cap is re-evaluated at approval and reconciliation only; creation and revision do not test it (resolves the §2.5 rung 9 vs §3.8 contradiction in the ladder's favour) — `routes/directives.py:103-123`
- §3.8 — insert — ambiguity — `actual_block_minutes` is a strictly positive integer — `routes/directives.py:152`
- §3.9 — insert — ambiguity — the three polymorphic references resolve in the order `hedge_program_id`, `hedge_instrument_id`, `tankering_directive_id`, so the first unresolvable one determines the 404 — `routes/exceptions.py:46-48`

### Coverage notes

Walked all 3,378 lines of `workspace/implementation/` (10 core modules plus 12 blueprints) and cross-checked four full inventories against the PRD: 57 routes vs the §4 table (exact match), per-endpoint role lists vs §2.1 (exact match), list filters vs §2.3 (exact match), and all 50 error codes vs §5 (exact match). Two divergences were deliberately left unpatched as non-observable: the contract `all_in_price_usd_per_gal` is recomputed on read rather than frozen at creation (the station fee is immutable, so the value can never differ), and the derived ledger fields are recomputed rather than stored (every mutating request cascades in-request, so no read can observe the difference). Pinning either would have meant adding prose about behaviour the API does not exhibit.

---

## Pipeline complete

`workspace/PRD_COMPLETED.md` exists on disk. Final state: 174/174 tests passing in all 8 parallel stability rounds (orchestrator-verified), 0 tests deleted, 0 implementation fixes required.
