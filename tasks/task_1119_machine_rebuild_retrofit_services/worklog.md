# Worklog — task_1119_machine_rebuild_retrofit_services

## Step 1: Create task directory — 2026-08-10T18:53:00.000Z

Pre-assigned output folder `tasks/task_1119_machine_rebuild_retrofit_services` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T19:30:00.000Z

All three scaffold artifacts are generated, lint-clean, and verified on disk.

## Files on disk

- `/home/ubuntu/github/CodingPRD/tasks/task_1119_machine_rebuild_retrofit_services/SCAFFOLD.yaml` — 1230 lines (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1119_machine_rebuild_retrofit_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 803 lines (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1119_machine_rebuild_retrofit_services/SCAFFOLD_CORNER_DESIGN.yaml` — 1223 lines (single top-level key `scaffold_corner_design`)

Lint verdict (verbatim, final run): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (71 endpoints, 13 entities, 18 §1.8 instances, 48 active §1.9 instances, 963 calls scanned, 0 violations.)

## Design summary ("harder than expert" calibration)

**Complexity profile**: workflow-orchestration primary + temporal-windowing secondary archetype; layers = dual-variant calculation, cascading side effects, optimistic concurrency, rate/threshold triggers; flat topology (all peer entities, FK-linked, no URL nesting of ownership); cyclic state-machine shape with a parallel commercial dimension; segregation-of-duties role model; immediate consistency.

**Entity model (13)**: Customer, Machine, Assessment (as-found measurements → computed wear_index/recommended_path), RebuildProject (central: decision, quote snapshot fields, rework/escalation counters, warranty fields), Part (self-referential supersession chain, stock/reservation counters), ProjectPartLine, ReverseEngineeringJob (obsolete-part RE), DowntimeWindow, ShipmentStage, AcceptanceTest (5-sample geometric accuracy), TrainingRecord, WarrantyClaim, TradeInOffer (stores both valuation variants).

**State machines (11)**: non-linear — RebuildProject carries a cyclic work dimension (AWAITING_ACCEPTANCE→REWORK→AWAITING_ACCEPTANCE, 3rd consecutive failure → ESCALATED) plus a parallel commercial dimension (QUOTE_DRAFT↔QUOTE_SENT→APPROVED); cycles also on ReverseEngineeringJob (fabrication failure loop) and Assessment (return/resubmit); bubble-up compound transitions (PASS → ACCEPTED auto-creates TrainingRecord; training completion → HANDOVER_READY); system sweeps on the logical clock (default `2026-05-01T00:00:00Z`).

**Calculations (13)**: dual variants on TradeInOffer residual value (MARKET_COMPARABLE 7,965,128 vs COST_APPROACH 12,000,000 cents for identical inputs) and AcceptanceTest evaluation (WORST_CASE vs ISO_STATISTICAL — same samples PASS at 12.0 / FAIL at 22.02); combinatorial formulas in distinct modes — quote pricing with pinned per-line-round-then-sum-then-tier-discount order (1-cent divergence observable: 7,299,998 vs 7,299,999) and clamped 3-input weighted wear_index; plus two pinned conservation invariants (part stock units; quote cents across trade-in apply/revoke) and rework surcharges (5%/10% of quote).

**Endpoints (71)**, errors (31, all triggerable and referenced), roles (9: Customer entity-backed, 8 opaque operational roles), 3 OCC concurrency rules (assessment/offer creation on Machine.version, quote recompute on RebuildProject.version), 10 ordered validation priorities.

**§1.8 difficulty design**: 18 instances — all 9 rules × exactly 2, each honoring its differentiation clause (different entity domains, modes, entities, triggers, error-category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities); every numeric assert is a code-computed literal.

**§1.9 corner design**: 53 entries = 49 active instances across 9 sections (entities 8, state_machines 12, calculations 3, validations 15, cross_cutting_layers 3 OCC, rbac 4, consistency_model 1, endpoints 2) + 4 `excluded_because` stubs citing §1.8 instances. All 71 instance names are unique across both design files.

## Step 3: Copy shared files — 2026-08-10T19:31:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1119_machine_rebuild_retrofit_services/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T19:45:00.000Z

All contracts pass. The PRD is complete on disk.

**Deliverable**: `/home/ubuntu/github/CodingPRD/tasks/task_1119_machine_rebuild_retrofit_services/workspace/PRD.md` — 353 lines.

**Section structure**
- **§1 Introduction** — 2 paragraphs (business context + lifecycle scope, `/api` mount, logical clock, segregation-of-duties framing)
- **§2 Global Specifications (11 subsections)** — 2.1 RBAC (headers, all 9 roles with exact spelling, per-role `identity:` prose: Customer entity-backed, 8 opaque roles individually named); 2.2 Response Structure (**byte-identical verbatim** copy of `section-2.2-response-structure.md`); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields); 2.4 Common Resource Properties & mutation semantics (all 13 entities carry `id`/`created_at`/`updated_at`/`version`); 2.5 Money/Microns/Rounding (integer cents, half-up at pinned points, 2-decimal microns); 2.6 OCC (all 3 rules with endpoint path, occ field, exact error id + 412, pure stale-version framing); 2.7 Logical Clock & sweeps (startup default `2026-05-01T00:00:00Z`, strict-inequality sweeps, lazy offer expiry); 2.8 Validation Gates in explicit priority order 1–10 with ordering consequences; 2.9 Stock Conservation invariant; 2.10 Quote & Trade-in Credit Conservation invariants; 2.11 Nested Resource Retrieval (left-to-right)
- **§3 Business Logic (9 subsections, scattered)** — 3.1 Customer/Machine registration; 3.2 Assessment & wear index (formula, thresholds 80.00/40.00, supersession, submit/return/accept cycle, project auto-creation with zero-initialized bookkeeping); 3.3 Decision & quote (override reason, pinned 6-step computation, tiers at $500k/$1M, $145/hr labor, send/approve gates, credit limit last); 3.4 Parts/obsolescence/RE (snapshots, 1.8 multiplier, atomic ascending stock gate, segregated RE cycle); 3.5 Downtime windows & staged shipment (half-open overlap, adjacency, closed-bound containment, 2-day sibling gap); 3.6 Acceptance/rework/escalation (both evaluation variants fully specified, inclusive tolerances, 5%/10% surcharges, REWORK vs ESCALATED at streak 3, RETRY/CANCEL); 3.7 Training & handover (1/2/3 sessions, bubble-up); 3.8 Delivery/warranty/claims (6/12/24 months, temporal-before-drift gate order, strict 15.0 drift); 3.9 Trade-in (both valuation branches fully specified, 12% depreciation, 0.25/0.50 condition factors, $20k scrap floor, lazy expiry, 3-link acceptance cascade, apply/revoke)
- **§4 Endpoint table** — 71 rows, 4 columns only (Method, Path, Description, Authorized Role(s))
- **§5 Error catalogue** — 31 rows, 2 columns only (Error ID, HTTP Status Code)

**Hard Contract Reports**
```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 96 required, 96 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: 10 gates, all expressed in ordered prose (§2.8 + per-endpoint orderings in §3), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint + expected_<parent>_version + error_id + 412), 0 missing
- state_machines[].transitions: 12 machines, all transitions (from/to, preconditions+error_id, side effects) expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed in precise prose (pinned evaluation order, constants embedded, no pseudocode/fuzzy words), 0 missing
- validations[] conditions: 31 error ids all matchable in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 71 endpoints checked, all side effects and scopes expressed, 0 missing
- entities[].fields[] structured content: defaults/initials/constraints reconstructible (patched revision_count=0, validated_by_id null, zero-initialized project bookkeeping), 0 missing
- sibling-branch symmetry: WORST_CASE/ISO_STATISTICAL, MARKET_COMPARABLE/COST_APPROACH, RETRY/CANCEL, REWORK/ESCALATED, PENDING/RESERVED-cancel — all symmetric, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 600
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage**: 13 entities, 12 state machines (every transition), 13 calculations, 10 validation priority gates, 71 endpoints, 31 errors, 9 roles, 3 OCC rules — all projected into prose. Fuzzy-word scan clean; §4/§5 table shapes conform.

**Two scaffold observations the caller should know** (rendered faithfully, not silently "fixed"):
1. The `AcceptanceTest.evaluation_variant` entity-field description ("WORST_CASE when decision == FULL_REBUILD") contradicts the calculations table, which states the mapping twice consistently (WORST_CASE for RETROFIT_ONLY/MECHANICAL_REBUILD, ISO_STATISTICAL for FULL_REBUILD). The PRD follows the calculations table.
2. `BASE_PRICE[decision]`, `BASE_HOURS[decision]`, `MARKET_BASE[machine_type]`, and `REPLACEMENT_COST[machine_type]` carry no numeric values in the scaffold, so the PRD refers to them as configured per-decision-class / per-machine-type constants without inventing numbers.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-10T20:10:00.000Z

Test generation complete for `task_1119_machine_rebuild_retrofit_services`. All outputs are under `/home/ubuntu/github/CodingPRD/tasks/task_1119_machine_rebuild_retrofit_services/`.

## File inventory (line counts)

**test_helpers/ (1,657 lines)**
- `types.py` 358 — 13 entity TypedDicts, 15 status/enum classes, 9-role UserRole
- `api_client.py` 234 — ApiClient(GenericApiClient), one method per PRD §4 endpoint (49 endpoints)
- `api_errors.py` 76 — 31 ApiErrorId members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` 184 — per-entity assertions + `assert_part_stock_conservation` / `assert_quote_conservation`
- `factories.py` 173 — payload factories, input fields only
- `constants.py` 74 — PRD-pinned constants only (explicitly excludes PRD-unpinned configured base prices/hours/market bases)
- `test_users.py` 67 — TEST_USERS + per-instance builders; `make_customer_headers` for the entity-backed Customer role
- `fixtures.py` 448 — tiered composite fixtures: scoped → decided → quoted → approved → sourced (incl. RE-job completion) → rebuild → awaiting-acceptance → accepted → handover-ready → delivered; trade-in and claim helpers
- `__init__.py` 43 — barrel export

**test_suite/ (2,112 lines)** — `conftest.py` 56 + 16 test files (82 tests):
test_01 customers/machines (6), test_02 assessment lifecycle (4), test_03 wear index/path (5), test_04 OCC (3), test_05 decision/quote (4), test_06 commercial gates (4), test_07 sourcing/stock (6), test_08 reverse engineering (3), test_09 acceptance (8), test_10 rework/escalation (5), test_11 windows/stages (6), test_12 training/delivery (5), test_13 warranty (7), test_14 trade-in (10), test_15 access control (5), test_16 project discovery (1).

## Coverage

- **Queue A (difficulty): 18/18 instances emitted, 36 tests (exactly ≥2 each).**
- **Queue B (corner): 46/48 non-stub instances emitted, 46 tests (1 each). 5 stubs correctly not translated** (all `difficulty_instance` cross-refs verified to resolve).
- **Total: 82 tests.**

## Skipped instances (PRD-first filter, with reasons)

1. `Corner/entities/assessment_computed_wear_index_input_ignored` — the PRD never states how unknown request body fields are handled; a strict-schema implementer could 400 the extra `wear_index` input, so "ignored" is not uniquely derivable.
2. `Corner/entities/system_fields_input_ignored` — same silence for client-supplied `id`/`version` on create.

## Key PRD-vs-design-index reconciliation

The PRD never pins the numeric values of per-decision-class base prices, base-hour allowances, or per-machine-type market bases/replacement costs (all described only as "configured"). Every design-index literal depending on them (quote totals like 67998770, residual values 7965128/12000000, surcharge 3399939/16999694, expires_at string) was re-derived instead: surcharges asserted as `round_half_up(live_quote × pinned 5%/10%)`, conservation asserted via the §2.10 identity, credit-limit tests armed deterministically with `credit_limit_cents=0` (quote provably positive from pinned line prices), warranty_end asserted as pinned date + delivery_date's own time suffix, offer expiry asserted as parsed created_at + exactly 30 days. Fully derivable literals were kept (wear indices, line totals 2399999/7299998, ISO statistic 22.02, drift 15.0/15.1, version +1 increments).

## Stage-2 tag audit result

Machine-checked via AST + yaml cross-reference (script run, then removed): 82/82 tests carry exactly one `Design:` line as the docstring's final line; 0 untagged, 0 dual-tagged, 0 malformed, 0 tags pointing at non-existent instances, 0 stub translations, 0 section/rule mismatches; all 64 cited instances resolve. Every `PRD §…` citation survives literal grep of PRD.md. `pytest --collect-only` imports and collects all 82 tests cleanly; pyflakes clean; zero `skip`/`skipif`/`xfail` markers; zero "scaffold" mentions in generated code.

## Step 6: Generate Implementation — 2026-08-10T20:10:00.000Z

Implementation complete and verified. Summary:

## File inventory — `tasks/task_1119_machine_rebuild_retrofit_services/workspace/implementation/` (27 files, 2,976 lines)

| File | Lines | File | Lines |
|---|---|---|---|
| start.sh | 10 | requirements.txt | 1 |
| app.py | 75 | db.py | 82 |
| errors.py | 55 | response.py | 42 |
| middleware.py | 56 | util.py | 242 |
| constants.py | 90 | calc.py | 161 |
| serializers.py | 21 | services.py | 166 |
| routes/__init__.py | 1 | routes/common.py | 50 |
| routes/customers.py | 34 | routes/machines.py | 73 |
| routes/assessments.py | 182 | routes/projects.py | 530 |
| routes/parts.py | 160 | routes/rejobs.py | 114 |
| routes/acceptance.py | 142 | routes/training.py | 83 |
| routes/windows.py | 96 | routes/stages.py | 190 |
| routes/claims.py | 151 | routes/offers.py | 144 |
| routes/clock.py | 25 | | |

## Confirmations

- **start.sh exists and is executable** (`-rwxrwxr-x`): foreground launcher, `exec python3 app.py`, guarded dependency install (`python3 -c "import flask"` check so per-test reboots skip pip), binds `0.0.0.0`, port from `$PORT` (default 10000).
- **71 registered (method, path) route pairs** — exactly the scaffold §1.5 endpoint table (Flask's built-in `/static` route was disabled via `static_folder=None` so it doesn't inflate the count).
- **Smoke boot succeeded**: fresh `bash start.sh` launch answered `GET /api/machines` with the correct envelope (`meta`/`response_type`/pagination fields), then shut down cleanly. Two full end-to-end waves also passed on separate fresh boots, covering the entire lifecycle: assessment → project auto-create → decision → OCC-gated quote → send/approve → atomic sourcing with ACTIVE/OBSOLETE split → RE-job segregation → rebuild → FAIL/REWORK/ESCALATED cascades with 5%/10% surcharges → stage parking/replan → PASS + training bubble-up → delivery/warranty → drift/temporal claim gates → clock sweeps with open-claim protection → trade-in valuation, supersession, lazy expiry, and apply/revoke conservation.

## Key design decisions

- **Storage**: in-memory dicts only, empty on every boot, zero seeding.
- **Logical clock**: fixed default `2026-05-01T00:00:00Z`, never wall-clock for business rules; `current_utc` echoes the verbatim set string; `created_at`/`updated_at`/computed datetimes serialized with 3 fractional digits per PRD §2.4; client-supplied datetimes echoed verbatim.
- **Validation gates** implemented in PRD §2.8 priority order (headers → role/ownership/segregation → body shape → existence → OCC → state → referential → temporal → structural → fiscal).
- **Money/microns**: `Decimal` with ROUND_HALF_UP at the pinned rounding points only; dual-variant acceptance evaluation follows PRD (FULL_REBUILD → ISO_STATISTICAL).
- The scaffold references but never pins four config tables (per-decision `BASE_PRICE`/`BASE_HOURS`, per-type `MARKET_BASE`/`REPLACEMENT_COST`); they live in `constants.py` as server configuration, with every pinned constant verbatim.
- Two defects caught and fixed by my own edge tests: the begin-sourcing stock gate now projects reservations cumulatively per part (atomicity), and trade-in apply distinguishes `ERR_TRADE_IN_NOT_APPLICABLE` (offer applied to another project) from `ERR_TRADE_IN_ALREADY_APPLIED` (same project already carries credit).

## Step 7: Run Tests and Iterate — 2026-08-10T20:20:00.000Z

## Summary

**Iterations run:** 2 (iteration 1: 77/82 in all 8 rounds, same 5 tests failing deterministically; iteration 2: 82/82 in all 8 rounds).

**Tests deleted:** none. No test was deleted; four test-layer fixes were applied under STEP 1c (partial-coverage split) and STEP 2 (test-vs-PRD consistency), each preserving every assertion the PRD verbatim-covers.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1119_machine_rebuild_retrofit_services/test_helpers/assertions.py` — `assert_acceptance_test`: the measurement-field block (`samples_microns` 5-list, `repeatability_microns`, `evaluation_variant`, `max_abs_sample_microns`, `statistic_value`) now applies only to recorded (`PASSED`/`FAILED`) tests; a born-`SCHEDULED` test returns early. PRD §3.6 supplies samples at *recording* time, so the helper's unconditional demand that a freshly scheduled test carry 5 samples contradicted the PRD's schedule-vs-record split (this was the bare `AssertionError` in `test_09 TestAcceptanceSchedulingGate.test_create_succeeds_after_declare_ready`).

**Fixes applied to `test_suite/` (1c splits — kept the covered instant/cascade assertions, dropped the unpinned serialization/source-state assertions):**
- `test_12_training_and_delivery.py` (`test_warranty_months_and_sessions_by_decision_class`, `TestDeliverRequiresAllStagesInstalled.test_deliver_succeeds_after_install_and_stamps_warranty`): `delivery_date == "2026-06-01T00:00:00Z"` string equality replaced with parsed-instant equality (`_parse_iso` helper added). PRD §3.8 pins "stamps `delivery_date` from the logical clock" (the instant) but never pins the serialization format for this field — §2.4's three-fractional-digit pin applies only to `created_at`/`updated_at` (and §2.1 to `api_request_timestamp`), so both verbatim echo and normalized-iso3 serializations are PRD-faithful (unique derivability collapse on format only). The format-agnostic `warranty_end == "<date>" + delivery_date[10:]` assertions were already passing and were kept untouched.
- `test_13_warranty_claims.py` (`TestWarrantyDriftBoundary.test_drift_just_above_15_admitted`): same treatment for `filed_at` (PRD §3.8: "The server stamps `filed_at` from the logical clock at filing" — instant pinned, format silent).
- `test_14_trade_in.py` (`TestTradeInAcceptCascade.test_accept_trades_in_machine_and_cancels_project`): removed the `machine["status"] == "TRADED_IN"` assertion for an `IN_PROJECT` machine. PRD pins the machine transition's source state twice — §3.1 "accepting a trade-in offer for a `REGISTERED` machine moves it to the terminal `TRADED_IN`" and §3.9 "the machine moves from `REGISTERED` to the terminal `TRADED_IN`" — and is silent on the IN_PROJECT case, so two PRD-faithful implementations diverge (scaffold's always-transition rule drove the original assertion). The verbatim-covered assertions (offer → `ACCEPTED`; PARTS_SOURCING project → `CANCELLED`) were kept.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in all 5 failures (null measurement fields pre-recording, iso3-stamped instants, REGISTERED-only machine transition).

**Final state:** all 8 parallel rounds report 82/82 passed, 0 failed, 0 errors. (Orchestrator verified on disk: results.1.json–results.8.json each passed=82 total=82 failed=0 errors=0.)

## Step 8: Finalize PRD — 2026-08-10T20:30:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1119_machine_rebuild_retrofit_services/workspace/PRD_FINALIZED.md` produced.

## Summary

**Line counts / delta:** PRD.md = 352 lines / 63,299 bytes; PRD_FINALIZED.md = 352 lines / 63,873 bytes. 0% line-count delta (edits are inline within existing paragraphs); +574 bytes (~+0.91% chars); 4 of 352 lines touched (~1.1%).

### Changes (3 logical fixes, 5 edit sites)

- **§3.6 — revise** — Born-`SCHEDULED` AcceptanceTest now explicitly carries null `samples_microns`, `repeatability_microns`, `evaluation_variant`, `max_abs_sample_microns`, and `statistic_value`, populated only at recording — `implementation/routes/acceptance.py:60-64` (create, all five `None`) and `:114-118` (record sets all five).
- **§3.8 — revise** — `delivery_date` pinned as "an ISO 8601 UTC timestamp with three fractional digits" — `implementation/routes/projects.py:444` (`clock.iso()`) → `implementation/util.py:15-20` (`iso3`), `implementation/db.py:29-30`.
- **§3.8 — revise** — `filed_at` pinned as "serialized as an ISO 8601 UTC timestamp with three fractional digits" — `implementation/routes/claims.py:89` (`clock.iso()`).
- **§3.9 — revise** — Trade-in accept cascade: machine → `TRADED_IN` only while still `REGISTERED`; a machine in any other status keeps its status while the project/line/job cascade still runs — `implementation/services.py:139-141` (status-guarded transition), `:142-146` (unconditional project cascade), `implementation/routes/offers.py:103-127` (no machine-state gate on accept).
- **§4 routing table — revise** — `/api/trade-in-offers/{id}/accept` row softened to "a still-REGISTERED machine becomes TRADED_IN" to keep the summary consistent with the patched §3.9 rule (same fix item).

### Per-edit pre-edit search log

1. **SCHEDULED-test null fields.** (a) Subject: AcceptanceTest measurement-field lifecycle. (b) Enumerated: `routes/acceptance.py:55-69` (create — only test-creation site), `routes/acceptance.py:94-142` (record — only mutation site), `calc.py:109-121` (`evaluate_acceptance`, called only from record), `serializers.py:6-17` (None → JSON null passthrough), grep for all five field names across `implementation/` confirming no other readers/writers. (c) Wording "populated only when the result is recorded" matches record-endpoint behavior exactly; no universal claim about other entities' fields.
2. **`delivery_date`/`filed_at` serialization.** (a) Subject: serialization format of server-stamped logical-clock fields. (b) Enumerated every iso3-stamped field: `created_at`/`updated_at` (`db.py:61,72`), `delivery_date` (`projects.py:444`), `warranty_end` (`projects.py:446`), `filed_at` (`claims.py:89`), `expires_at` (`offers.py:67`), `api_request_timestamp` (`response.py:13`) — all iso3; and every verbatim-echo field: `starts_at`/`ends_at` (`windows.py:50-51`), `planned_ship_date`/`planned_return_date` (`stages.py:72-73,183-184`), `current_utc` (`clock.py:25`). (c) Wording kept field-scoped (no "all timestamps" universal, which the verbatim-echo fields would falsify); phrase reused verbatim from §2.4's existing `created_at`/`updated_at` pin for terminological uniformity. `warranty_end`/`expires_at` deliberately left unpinned (no Step 7 fix traces to them; prefer under-determination).
3. **Trade-in machine transition.** (a) Subject: machine `status` behavior on offer acceptance. (b) Enumerated every machine-status write: `machines.py:47` (born REGISTERED), `assessments.py:69-70` (→UNDER_ASSESSMENT), `assessments.py:149` (→ASSESSED), `projects.py:271-272` (→IN_PROJECT), `projects.py:449-450` (→RETURNED), `services.py:139-140` (→TRADED_IN, REGISTERED-only); plus cascade internals `services.py:65-94` (`cancel_project_cascade` never touches the machine) and accept gate `offers.py:103-127` (no machine-state check). Also checked PRD §3.1:144 (already REGISTERED-scoped, kept verbatim) and §4:309 (overclaimed; softened as part of the same fix). (c) Wording explicitly scopes the keep-current-status clause to the machine and states the remaining cascade links apply regardless, so the unconditional project/line/job cancellation in `services.py:142-146` is not narrowed.

No other edits: the remaining two Step 7 items (test_12/test_13 helper-level `_parse_iso` parsing, `assert_acceptance_test` helper gating) were pure test-layer fixes with no additional PRD-silence beyond what edits 1–3 pin; the implementation itself was PRD-faithful everywhere, so no `implementation/` mismatch needed prose correction.

## Step 9: Complete PRD — 2026-08-10T20:40:00.000Z

## Summary

**Files**: Source `PRD_FINALIZED.md` (352 lines, 63,667 chars) → `PRD_COMPLETED.md` (352 lines, 67,179 chars; **+3,512 chars**, +0 lines — all edits are in-paragraph inserts/revisions, no new sections or paragraphs).

**Counts**: 19 ambiguity-pins, 1 mismatch-revision (the §3.4 line-cancel `quote_stale` clause, which previously asserted an unconditional raise; revised to the impl's revision≥1-scoped behavior).

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.1 — insert — ambiguity — Customer callers on list endpoints see only owned resources (ownership resolved through parent chain); other roles unfiltered — routes/common.py:39-50, list handlers
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — response.py:13, util.py:23-25
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped to bounds (not rejected); non-integer values → `ERR_INVALID_REQUEST` — util.py:207-230
- §2.4 — insert — ambiguity — `version` starts at 1 at resource creation — db.py:64
- §2.7 — revise — mismatch/ambiguity — clock "advance" → "set": any parseable ISO 8601 instant accepted, no monotonicity; `current_utc` echoes the supplied `to_iso8601` string verbatim — routes/clock.py:17-25, db.py:18-30
- §3.2 — insert — ambiguity — `scope_notes` required but may be an empty string — routes/assessments.py:28
- §3.2 — insert — ambiguity — project birth fields also include `decision_reason`, `assigned_engineer_id`, `warranty_months` null; accept response returns the updated assessment, not the new project — routes/assessments.py:152-182
- §3.3 — insert — ambiguity — decision write stamps `warranty_months` (6/12/24) onto the project and stores `decision_reason` (null when absent, even on matching decision) — routes/projects.py:104-108
- §3.3 — insert — ambiguity — recompute while `APPROVED` permitted and leaves `APPROVED` intact (only `QUOTE_SENT` reverts) — routes/projects.py:144-146
- §3.3 — insert — ambiguity — quote-send gate order: commercial-state check (`ERR_INVALID_STATE`) precedes `ERR_QUOTE_REQUIRED` and `ERR_QUOTE_STALE` — routes/projects.py:155-166
- §3.4 — insert — ambiguity — supplied `superseded_by_id` must reference an existing part, else `ERR_NOT_FOUND` — routes/parts.py:43-44
- §3.4 — insert — ambiguity — stock gate projects sibling `PENDING` lines' reservations cumulatively per part — routes/projects.py:228-243
- §3.4 — revise — mismatch — line cancellation (PENDING and RESERVED) raises `quote_stale` only once at least one quote has been computed — routes/parts.py:156-159
- §3.4 — insert — ambiguity — RE job born with `re_cost_cents` and `fabricated_by_id` null (in addition to pinned `revision_count`/`validated_by_id`) — routes/projects.py:257-268
- §3.5 — insert — ambiguity — operator-supplied instants (`starts_at`, `ends_at`, `planned_ship_date`, `planned_return_date`) stored and echoed verbatim, not renormalized — routes/windows.py:50-51, routes/stages.py:72-73
- §3.5 — insert — ambiguity — `stage_sequence` uniqueness not enforced (informational label) — routes/stages.py:48
- §3.5 — insert — ambiguity — replan revalidates only containment and sibling gap; the referenced window's status is not re-examined — routes/stages.py:181-189
- §3.6 — insert — ambiguity — recording a result requires the test still `SCHEDULED`, else `ERR_INVALID_STATE` — routes/acceptance.py:104-109
- §3.7 — insert — ambiguity — begin-training response returns the updated TrainingRecord object — routes/projects.py:417
- §3.8 — insert — ambiguity — `warranty_end` day-of-month clamped to target month's last day when shorter — util.py:47-62
- §3.8 — insert — ambiguity — `measured_positioning_microns` on a `MECHANICAL_DEFECT` filing is validated (non-negative) and stored, never enters drift computation — routes/claims.py:49-50,87
- §3.9 — insert — ambiguity — accept gates order: `OFFERED`-state check (`ERR_INVALID_STATE`) precedes lazy expiry evaluation — routes/offers.py:107-122
- §3.9 — insert — ambiguity — trade-in apply/revoke carry no project work-state or commercial-state precondition — routes/projects.py:481-530

The four "configured" server tables in `implementation/constants.py` (per-decision-class base prices/base hours; per-machine-type market bases/replacement costs) were left as "configured" per the acknowledged under-determination.
