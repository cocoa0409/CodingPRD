# Worklog — task_1308_blow_molding_bottle_plant

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

RESUME RUN: directory `tasks/task_1308_blow_molding_bottle_plant/workspace/` already existed (created by the prior terminated run); treated as DONE per resume instructions. Directory was verified empty of all other artifacts (no SCAFFOLD, no PRD, no tests, no implementation) — pipeline resumes from Step 2.

## Step 2: Generate Scaffold — 2026-08-12T19:24:00.000Z

Scaffold generation complete for task_1308 (blow molding & bottle plant). All three artifacts written and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/SCAFFOLD.yaml` — 1266 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 720 lines (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/SCAFFOLD_CORNER_DESIGN.yaml` — 1514 lines (single top key `scaffold_corner_design`)

## Counts
- Entities: 14 · State machines: 13 (65 transitions) · Calculations: 8 · Validations: 59 ordered rows (P1–P10, 8 categories) · Endpoints: 79 · Errors: 50 · Roles: 6 · OCC concurrency rules: 4
- §1.8: 18 instances (9 rules × 2) · §1.9: 71 instances (67 active + 4 `excluded_because` stubs), 1024 structured calls scanned
- Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Notable design decisions
- **Archetype blend**: workflow_orchestration + pricing_engine; flat topology, cyclic state machines, segregation-of-duties role model (quality-lot disposition must come from a different QT than the result recorder), immediate consistency, logical clock with mandatory `2026-08-01T00:00:00Z` default.
- **Dual-variant calcs on different domains**: warehouse-vs-blow-on-site freight comparison (Shipment/spec domain; literal 197880 vs 131880 cents → BLOW_ON_SITE) vs provisional-vs-actual resin reconciliation (MaterialLot/run domain; 352.0 vs 360.0 kg, 2.27% ≤ 3.0% tolerance).
- **Combinatorial modes (a) and (b)**: cycle-throughput with weight-driven cycle time, nested `min` against the inline-labeler 240 cph cap, and blockout-derated cavitation (10.16 s → 1396 bph vs uncapped 2062); freight pins per-pallet dim-weight rounding (855.25→855.3 ×3 = 2565.9 kg, beating the forbidden aggregate-then-round 2565.8) and per-tier-then-sum cent rounding.
- **Non-linear machines on different entities**: spec revision/re-qualification loop gated on `content_revision > rejected_revision`; quality-lot auto-fork (ACCEPTED/REJECTED by AQL band) with REJECTED→PENDING rework loop and `retest_count`.
- **Cascades**: QC rejection drives lot→order HELD→slot CANCELLED→line CHANGEOVER (depth 3); customer suspend drives customer→orders→slots (depth 2).
- **Two interval semantics**: half-open schedule slots with mold-snapshot-dependent changeover buffer (0 same mold / 90 min different, `>=` inclusive) vs closed dock windows where touching endpoints conflict.
- **Compensating invariants**: resin kg conservation across run close/void (500 == available+consumed+purge, zero drift) and accepted-bottle conservation across book/cancel (accepted == unallocated+reserved+shipped).
- **OCC** on mold version (blockout create), order version (schedule/reschedule supersede), spec version (qualification-run create pins `content_revision`); all test recipes use `${var}`-captured versions, per lint rule (e).
- All formula-derived asserts were pre-computed and verified by script (freight 195000/195042/228954, variance boundary 3.00-vs-3.01, AQL 280/281 band edge, purge 150.0 kg DARK→CLEAR, FIFO waterfall 100/50 split, summary rollup 12000/11880/2928/8952).

## Step 3: Copy Shared Files — 2026-08-12T20:44:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1308_blow_molding_bottle_plant/workspace/INSTRUCTION.md` (1424 bytes). All three scaffold artifacts verified present (SCAFFOLD.yaml 1266 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 720 lines, SCAFFOLD_CORNER_DESIGN.yaml 1514 lines).

## Step 4: Generate PRD — 2026-08-12T20:44:00.000Z

The PRD is complete and all three hard contracts pass. Here is the final summary.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/workspace/PRD.md` — 348 lines.

**Section structure:**
- **§1 Introduction** — 2 paragraphs (business context of freight-of-air economics + operational principles)
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (headers, 6 roles, identity translations incl. `entity_backed:Customer` for `CustomerQualityRep`), 2.2 Response Structure (byte-identical to the canonical `section-2.2-response-structure.md`, verified by substring match), 2.3 Pagination, 2.4 The Logical Plant Clock (default `2026-08-01T00:00:00Z`), 2.5 Common Resource Properties, 2.6 Nested Resources & Identifier Resolution (all 13 per-entity 404s + `ERR_RATE_CARD_NOT_FOUND`), 2.7 OCC (all 4 rules), 2.8 Precision/Rounding, 2.9 Validation Pipeline (10-tier priority ladder + same-tier tiebreak), 2.10 Cascading State Consistency
- **§3 Business Logic** — 8 subsections organized by material flow: 3.1 Customers/Credit/Rate Cards, 3.2 Specs & Qualification Loop, 3.3 Molds/Lines/Blockouts (+ throughput preview), 3.4 Material Lots, 3.5 Orders & Scheduling, 3.6 Runs (start/close/void), 3.7 Quality & AQL, 3.8 Freight/Shipments/Dock
- **§4 Endpoint table** — 79 rows = 79 scaffold endpoints, 4 columns only
- **§5 Error catalogue** — 50 rows = 50 scaffold errors, 2 columns only

**Zero-Silence coverage audit (§1.1–§1.7):**
- §1.1 entities: all 14 entities, all 113 fields named in backticks with types/defaults/nullability/computed derivations in prose (e.g., `requires_inline_labeler` derivation, `available_kg` never negative, `weight_tolerance_pct` default 2.0)
- §1.2 state machines: all 13 machines, every transition's from/to states, preconditions paired to error IDs, and every side effect (suspend cascade, spec-edit cascade with post-increment `rejected_revision` pin, hold/QC-reject cascades, run-close 6-part cascade, void's exact compensating credit + 3-way lot recompute + color-memory rebuild, shipment↔appointment bidirectional reverts including the cancel-vs-no-show asymmetry)
- §1.2.1 concurrency: all 4 OCC rules with write-endpoint framing, `expected_*_version` fields, `ERR_STALE_VERSION`/412
- §1.3 calculations: all 8 expressed as reconstructible prose with every constant (10.0s base cycle, 0.08 s/g, 240 cph labeler cap, 0.97 yield; AQL bands 280/1200/10000 with per-band n/c_leak/c_drop; dim divisor 6,000 cm³/kg, pallet cube 144,000 cm³, tare 20 kg, 1,500/30,000 per pallet, truck 96,000,000 cm³ and 24,000 kg; 40¢ on-site fee with tie-to-WAREHOUSE; variance strictly-greater-than 3.0 with the exact-3.00 non-alert; 1.05 release uplift; 90-min/0-min changeover buffer; FIFO `created_at`/`lot_code` waterfall with purge-first per-lot debit and all-or-nothing failure)
- §1.4 validations: full priority ladder in §2.9 plus every check paired with its error ID near its workflow in §3
- §1.5 endpoints: all 79 in §4; side effects narrated in §3
- §1.6 errors: all 50 in §5 and mentioned in §2/§3 prose
- §1.7 roles: all 6 with exact spelling and identity semantics

**Hard-contract reports:**
```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].request_body (+named outputs): 95 required, 95 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS

Rule coverage check:
- validations priority ordering: 10 tiers expressed as an ordered pipeline in §2.9, 0 missing
- concurrency_rules OCC: 4 checked, 4 expressed (endpoint + occ field + ERR_STALE_VERSION/412), 0 missing
- state transitions: all from/to pairs, preconditions, side effects expressed, 0 missing
- calculations: 8 checked, 8 fully expressed with constants and pinned rounding orders, 0 missing
- validation conditions: 47 rows matchable to error_ids in prose, 0 missing
- endpoint side effects / applies_to scopes: expressed, 0 missing
- field structured content: defaults/nullability/computed derivations reconstructible, 0 missing
- sibling-branch symmetry: AQL bands, purge matrix 9 cells + null row, review decisions, dispositions, cancel branches — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 730
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable scattering/indirection choices:**
- Freight-of-air is deliberately split three ways: rate-card mechanics in §3.1, the warehouse-vs-blow-on-site comparison (with the 40¢ on-site fee and tie-break) in §3.2 under the spec narrative, and the full charge formula (pinned per-pallet dim-weight rounding, per-tier cent rounding, truck cube/payload caps) in §3.8.
- OCC rules are stated mechanically in §2.7 but re-motivated in each workflow subsection (blockout create in §3.3, schedule/reschedule in §3.5, qualification create in §3.2).
- `weight_tolerance_pct` is introduced on the spec in §3.2, then reused for order-create tolerance in §3.5 and qualification `weight_within_tolerance` in §3.2/§3.6-adjacent text without repeating the definition verbatim.
- The 90-minute mold-change buffer hangs off the `ScheduleSlot.mold_id` snapshot semantics (0 min when adjacent slots share the snapshot), forcing the reader to combine schedule-slot creation with the overlap rule.
- The qualification approval pin check (`spec_revision_pinned` vs current `content_revision`) is attributed to the generic `ERR_INVALID_STATE` since the scaffold nominates no specialized error for it; this is stated explicitly rather than left silent.
- Debugging note: the first verification script pass produced false "missing" results because naive backtick pairing is thrown off by the §2.2 JSON code fences; the final checks strip fenced blocks before extraction, which is the correct procedure.

## Step 6: Generate Implementation — 2026-08-12T21:45:00.000Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, guarded pip install |
| `requirements.txt` | 1 | flask only |
| `app.py` | 47 | Entry point, ApiError/404/405/500 envelope handlers, blueprint registration, `app.run(host="0.0.0.0", port=$PORT)` |
| `db.py` | 33 | In-memory dict store; starts empty every boot; logical clock default 2026-08-01T00:00:00Z |
| `errors.py` | 79 | ApiError + all 45 catalog error IDs with exact HTTP statuses |
| `envelope.py` | 43 | `meta`/`response_type`/`data` envelope; pagination meta (limit/offset/total_count/has_more) |
| `auth.py` | 32 | X-User-ID/X-User-Role auth, 6-role RBAC check |
| `util.py` | 85 | UUIDs, monotonic wall timestamps (3-fractional-digit ISO), logical clock, ISO parsing, Decimal serialization |
| `validate.py` | 175 | Shape validation (required/unknown fields, enums, non-negative numerics, datetimes, tiers), pagination/filter parsing |
| `calc.py` | 190 | All 7 calculation rules |
| `services.py` | 567 | 14 serializers, derived rollups, cascades, waterfall debit/reversal, overlap + credit checks |
| `routes/` (14 files) | 1,992 | One module per resource group |

## Endpoints
**79/79** routes from the PRD §4 table implemented and verified registered at runtime (clock, customers ×5, rate cards/quotes ×3, lines ×5, molds ×5, blockouts ×4, specs ×8, qualification runs ×5, material lots ×6, orders ×11, runs ×5, quality lots ×5, shipments ×8, dock appointments ×7, slots ×2).

## Coverage
- **State machines**: all 12 entity machines with preconditions, terminal-state `ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE` split, and side effects (suspend cascade, spec-edit cascade in PRODUCTION_ACTIVE with `rejected_revision` pinning, QC-reject → order HELD → slots cancelled → line RUNNING→CHANGEOVER, shipment↔appointment bidirectional reversion including no-show).
- **Calculations**: freight-of-air with pinned per-pallet dim-weight rounding then per-tier cent rounding; logistics comparison with WAREHOUSE tie-break; throughput (2dp half-up cycle, unrounded cph, labeler cap 240, floor output); AQL bands with inclusive-accept boundary; reconciliation with strict &gt;3.00 variance alert; purge matrix with null-color-memory 0.0; FIFO waterfall (created_at ASC, lot_code tiebreak, purge-then-consumption per lot, all-or-nothing) with exact void reversal.
- **Validations**: full priority pipeline (auth → role/cross-customer/SoD → shape → existence left-to-right → OCC-before-state → terminal/state/specialized → safety → temporal → constraint → referential → fiscal), verified by tests including 400-before-404 ordering.
- **RBAC**: exact role lists per endpoint; `CustomerQualityRep` entity-backed ownership (403 `ERR_CROSS_CUSTOMER_ACCESS`); segregation of duties on disposition.
- **OCC**: all 4 guarded endpoints with `ERR_STALE_VERSION` 412 checked before other state rules.

## start.sh contract
Verified live: honors `$PORT` (tested on two ports), binds `0.0.0.0`, `exec python3 app.py` in foreground, pip install guarded by `import flask` probe so per-test reboots skip reinstall. Store confirmed empty on fresh boot (`total_count: 0`); no seeding anywhere.

Verified via 4 smoke suites against fresh boots: full happy-path (customer→qualify→schedule→release→run→close→QC accept→ship→book→load→dispatch→deliver→complete), QC reject/rework/SoD, void reversal with color-memory recompute, variance boundary (3.00 → no alert), schedule overlap + same-mold 0-min vs different-mold 90-min buffer, credit-limit 402, spec-edit cascade, no-show/appointment-cancel reversion, pagination, and error-shape checks. Hand-verified freight figures match the pinned rounding orders (e.g., 7900 bottles → dim 5410.7 kg, 43,286 cents).

## Step 5: Generate Unit Tests — 2026-08-12T22:30:00.000Z

Generation complete. Summary:

## Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/test_helpers/`):
- `types.py` — 20 status/enum types + 14 entity TypedDicts (all entities carry `common_fields: true`, so all include id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (75 methods), GET endpoints passing filters via `params`
- `api_errors.py` — all 50 error IDs with §5 HTTP statuses, registered via `set_error_http_status_map` at import
- `assertions.py` — per-entity structure assertions plus `assert_material_lot_conservation` (received = available + consumed + purge) and `assert_order_stock_conservation` (accepted = unallocated + reserved + shipped)
- `factories.py` — 17 payload factories, input fields only
- `constants.py` — throughput/purge/AQL/freight constants and standard logical-clock timestamps
- `test_users.py` — six role header sets; `CustomerQualityRep` is `entity_backed:Customer`, so `make_customer_quality_rep_headers(customer_id)` threads the real Customer.id on ownership-gated review calls; QT builder for segregation-of-duties tests
- `fixtures.py` — 5-tier composites: single-entity creators, the qualification loop (`qualify_spec`), order lifecycle (`schedule_order` re-reads/captures OCC versions), and full scenarios (`setup_released_scenario` → `setup_running_scenario` → `setup_closed_run_scenario` → `setup_accepted_stock_scenario` → `setup_shipment_with_appointment` / `setup_booked_shipment`)
- `__init__.py` — barrel export

**test_suite/** (12 files): `conftest.py` + 11 numbered test files, 104 tests total.

## Queue counts

- **Queue A (Difficulty): 18/18 instances translated, exactly 2 tests each (36 tests).** Both priority-pair instances were kept because PRD §2.9 explicitly fixes the stage order ("a failure at an earlier stage masks every later stage" + the fifth/sixth/seventh/tenth stage enumeration), making the masking outcome uniquely derivable.
- **Queue B (Corner): 66/67 non-stub instances translated (68 tests; two instances got 2 tests). 1 instance skipped:** `Corner/state_machines/blockout_clear_twice_returns_already_terminal` — PRD never declares `CLEARED` terminal for cavity blockouts, so a second clear could be `ERR_ALREADY_TERMINAL` or `ERR_INVALID_STATE` under two faithful readings (two-condition filter, unique-derivability failure). The 4 `excluded_because` stubs were not translated; all their difficulty-instance pointers resolve.
- Two instances were generated with narrowed assertions rather than skipped: `customer_create_applies_defaults` drops `version == 1` (PRD never pins the initial version value) and `get_missing_rate_card_returns_not_found` keeps only the freight-quote-without-ACTIVE-card half (PRD §2.6's per-entity not-found list omits FreightRateCard, so GET-by-absent-id's error id is not uniquely derivable).

## Design-tag audit result

104 tests, 104 `Design:` tags, each the final docstring line, all resolving to real instances; per-instance minimums met (Difficulty ×2, Corner ×1); the only shortfall is the intentional skip above. A separate verbatim sweep extracted every quoted span from every test docstring and confirmed all survive a literal (whitespace-normalized) grep of PRD.md — this required un-wrapping all citation sentences onto single lines and replacing editorial ellipses with contiguous PRD substrings.

## Notable fixture/factory decisions

- All kg-sum assertions derived from non-exact 2dp inputs (e.g. 362.56+362.6, per-pallet dim 855.3×3) use `pytest.approx(abs=1e-6)` — tight enough to still discriminate the PRD-forbidden aggregate-then-round freight variant (2565.8 vs 2565.9); integer cents stay exact.
- OCC tests capture versions from responses and assert stale-vs-fresh relationally, never absolute version numbers (initial version is not PRD-pinned).
- The dark→clear purge fixture sequences two qualified specs on one line: DARK order completes fully (run closed, lot accepted at 0/0, order completed → line rests at CHANGEOVER with `last_color_class` DARK) before the CLEAR order releases and runs inside its own adjacent slot.
- Timestamp echoes are asserted by day (`startswith("2026-08-03")`) since verbatim echo format is not PRD-pinned; the `created_at` three-fractional-digits check accepts `Z` or `+00:00` UTC offsets.

## Step 7: Run Tests and Iterate — 2026-08-12T22:50:00.000Z

Step 7 test/iterate loop is complete. Final summary:

## Summary

**Iterations run: 3** (iteration 1: baseline diagnosis; iteration 2: confirmed fixes but hit environmental flake; iteration 3: clean exit — all 8 rounds 104/104).

**Tests deleted: none.**

**Failures diagnosed (union across rounds, iteration 1):** exactly 2 deterministic failures, identical in all 8 rounds (no test-logic flakiness observed).

### Fixes applied to `implementation/`

1. **`workspace/implementation/routes/runs.py` — `close_run`**: the close endpoint treated both `CLOSED` and `VOIDED` as terminal, returning `ERR_ALREADY_TERMINAL` on a second close. PRD §3.6 declares only `VOIDED` terminal for runs ("The run itself moves from `CLOSED` to `VOIDED`, and `VOIDED` is terminal"), so closing a `CLOSED` run is an undefined transition and must surface `ERR_INVALID_STATE` per §2.9. Split the guard: `VOIDED` → `ERR_ALREADY_TERMINAL`; non-`OPEN` → `ERR_INVALID_STATE`. (Fixes `test_close_twice_rejected_and_no_double_debit`.)

2. **`workspace/implementation/start.sh`**: replaced the per-boot `python3 -c "import flask"` dependency probe (a full flask import — the dominant boot cost, paid twice per boot) with an `importlib.util.find_spec('flask')` probe that resolves the spec without importing. This shrinks the server-boot window that the runner's 15s per-test restart poll was intermittently exceeding under heavy neighbor load on the shared host (iteration 2's sole failure mode: one `setup ERROR` per round, "API server could not be restarted", always ~87% through the round; an orphaned server process from a sibling task's sweep confirmed external load as the cause).

### Fixes applied to `test_helpers/`

3. **`test_helpers/factories.py` — `create_material_lot_payload`**: the factory always injected the default `resin_type: "PET"` even when a caller overrode `material_type="COLORANT"`, so every COLORANT creation payload violated PRD §3.4 ("a colorant lot must name its `color_code` and carries no `resin_type`") and the PRD-faithful implementation correctly rejected it with 400. The factory now drops the cross-field for the resolved `material_type` unless the caller explicitly supplied it (preserving future negative-test capability). (Fixes `test_dark_to_clear_purge_debits_lot`; the same latent bug existed at `fixtures.py:321` but no test exercised that path.)

### Validation
- Iteration 3: **all 8 parallel rounds passed 104/104, 0 failed, 0 errors** — stable exit.
- No tests weakened, no implementation checks removed, no PRD-untraced behavior added; `worklog.md` and `SCAFFOLD*.yaml` untouched.

## Step 8: Finalize PRD — 2026-08-12T22:58:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 347 lines; `PRD_FINALIZED.md`: 347 lines; **0% line-count delta** (both edits are inline sentence insertions within existing paragraphs — no new sections).

## Changes (one bullet per edit)
- **§3.4 — revise** — After the `material_type`/`resin_type`/`color_code` sentence, inserted: the conditional shape rules are enforced at the request-shape stage; omitting the required field or supplying the other material type's cross-field is rejected with `ERR_INVALID_REQUEST` — `implementation/routes/materials.py:43-56`.
- **§3.6 — revise** — After "Only an `OPEN` run whose order is still `RUNNING` can close.", inserted: closing a `CLOSED` run is an undefined transition → `ERR_INVALID_STATE`; closing a `VOIDED` run → `ERR_ALREADY_TERMINAL` — `implementation/routes/runs.py:219-222`.

## Step-7 items not edited into the PRD
- **`start.sh` find_spec probe**: boot-time optimization with no behavioral surface; the PRD does not specify launcher internals. No edit.
- **`fixtures.py:321` latent bug** (mentioned inside item 3): a test-fixture bug on a path no test exercises; it reveals nothing beyond what the §3.4 edit already pins. No separate edit.

## Per-edit pre-edit search log

**Edit 1 (§3.4 material-lot conditional shape)**
- (a) Subject: material-lot create cross-field/required-field validation (`material_type` vs `resin_type`/`color_code`).
- (b) Paths enumerated: `implementation/routes/materials.py` `create_lot` (lines 30-72 — the only lot-creation path; confirmed by repo-wide grep for `color_code`/`resin_type` across `implementation/`), `list_lots` filter (lines 76-93, read-only), `services.py:276-277` `ser_material_lot` (response emits both keys, null when absent — request-side wording cannot misdescribe it), `validate.py:68-126` `check_fields` (explicit JSON null treated as absent), `runs.py:61-76` (consumes lot ids, never creates lots), `services.py:75-87, 510` (resin-lot matching reads only).
- (c) Adjustment: phrased as "supplies the other material type's field" (a value), deliberately not claiming explicit-`null` payloads are rejected, since `check_fields` drops nulls before the cross-field check — keeps wording consistent with `validate.py` null-as-absent semantics.

**Edit 2 (§3.6 close-run state guard)**
- (a) Subject: terminal/undefined-state error selection on the run close transition (`CLOSED` vs `VOIDED`).
- (b) Paths enumerated: `implementation/routes/runs.py` `close_run` (lines 205-286: `VOIDED` → `ERR_ALREADY_TERMINAL`, non-`OPEN` → `ERR_INVALID_STATE`, order-not-`RUNNING` → `ERR_INVALID_STATE`), `void_run` (lines 289-316: `VOIDED` → `ERR_ALREADY_TERMINAL`, non-`CLOSED` → `ERR_INVALID_STATE`), plus every other `CLOSED`/`VOIDED` reference repo-wide: `services.py:98,103` (order rollups over non-`VOIDED` runs), `services.py:559-562` (`recompute_line_color` over `CLOSED` runs), `orders.py:309` (completion gate), `quality.py:17-18` (quality-lot terminal set — a different entity).
- (c) Adjustment: scoped the sentence to the close transition only ("a close attempted against..."), so it makes no universal claim about other transitions from `CLOSED` (e.g., `CLOSED` → `VOIDED` via void remains governed by the existing void paragraph) and leaves the order-not-`RUNNING` guard under the existing "Only an `OPEN` run whose order is still `RUNNING` can close" prose.

## Step 9: Complete PRD — 2026-08-12T23:20:00.000Z

All edits applied and verified. The diff is clean — 26 in-place edits, 3 added table rows, no new sections.

## Step 9 Summary — PRD_COMPLETED.md produced

**File stats**
- Source: `PRD_FINALIZED.md` — 347 lines / 64,411 chars (64,603 bytes)
- Output: `/home/ubuntu/github/CodingPRD/tasks/task_1308_blow_molding_bottle_plant/workspace/PRD_COMPLETED.md` — 350 lines / 68,300 chars (68,518 bytes)
- Delta: +3 lines (the 3 new §5 catalogue rows), +3,889 chars

**Counts: 26 ambiguity-pins, 3 mismatch-revisions (29 changes total)**

**Change log**
- §2.2 — revise — mismatch — error-envelope intro broadened from "4xx status codes" to "4xx and 5xx" since the server also emits `ERR_INTERNAL` (500) — implementation/app.py:34-36
- §2.2 — insert — ambiguity — pinned catch-all error ids: unmatched route → `ERR_NOT_FOUND` (404), wrong method → `ERR_METHOD_NOT_ALLOWED` (405), server failure → `ERR_INTERNAL` (500) — implementation/app.py:24-36
- §5 — insert — ambiguity — three catalogue rows for `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_INTERNAL` — implementation/app.py:24-36
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected); non-integer values → `ERR_INVALID_REQUEST` — implementation/validate.py:129-149
- §2.3 — insert — ambiguity — `total_count` counts filtered rows before pagination; `has_more` true iff `offset` + page size < `total_count` — implementation/envelope.py:27-34
- §2.3 — insert — ambiguity — enum filter value outside its declared set → `ERR_INVALID_REQUEST` — implementation/validate.py:152-160
- §2.4 — insert — ambiguity — logical clock owns `blocked_at`/`cleared_at`/`started_at`/`ended_at`; `created_at`/`updated_at`/`api_request_timestamp` are wall-clock UTC — implementation/util.py:18-26, envelope.py:16-19
- §2.5 — insert — ambiguity — resources are created with `version` 1 — implementation/services.py:26
- §2.5 — insert — ambiguity — non-system datetime fields serialize at whole-second precision when no sub-second component, else 3 fractional digits — implementation/util.py:42-49
- §2.8 — insert — ambiguity — integral numeric values serialize as JSON integers; non-integral as JSON numbers — implementation/util.py:69-85
- §2.9 — insert — ambiguity — malformed/non-object JSON body is itself a shape violation; explicit JSON null treated as an absent field — implementation/validate.py:19-27, 76-84
- §2.6 — insert — ambiguity — rate-card read by unresolvable id → `ERR_RATE_CARD_NOT_FOUND` — implementation/routes/freight.py:69-76
- §3.1 — insert — ambiguity — customer bottle-spec list accepts an optional `status` filter — implementation/routes/customers.py:98-115
- §3.2 — revise — mismatch — qualification-run create against a `RETIRED` spec → `ERR_ALREADY_TERMINAL` (PRD said any other state → `ERR_INVALID_STATE`) — implementation/routes/qualifications.py:53-57
- §3.2 — insert — ambiguity — on `APPROVE`, the revision-drift check (state rule) precedes the weight gate, so both failing surfaces `ERR_INVALID_STATE` — implementation/routes/qualifications.py:159-167
- §3.2 — insert — ambiguity — a spec's qualification runs are listable with an optional `status` filter — implementation/routes/specs.py:214-229
- §3.2 — insert — ambiguity — logistics-comparison `quantity` must be a non-negative integer, else `ERR_INVALID_REQUEST` — implementation/routes/specs.py:237-240
- §3.3 — insert — ambiguity — `CLEARED` is terminal (re-clear → `ERR_ALREADY_TERMINAL`); blockout list takes an optional `status` filter — implementation/routes/molds.py:217-218, 181-195
- §3.3 — insert — ambiguity — throughput-preview's `mold_id`/`bottle_spec_id`/`planned_weight_g` are all required query params; `planned_weight_g` must be a non-negative number — implementation/routes/lines.py:99-109
- §3.5 — insert — ambiguity — orders are created with `spec_revision_baseline` null — implementation/routes/orders.py:136
- §3.5 — revise — ambiguity — credit gate counts the order being scheduled exactly once (sum runs over the customer's *other* open orders plus this order's value) — implementation/services.py:459-475
- §3.5 — insert — ambiguity — every order representation embeds the full rollup block including `quantity_open_qc`; the summary read omits it — implementation/services.py:288-300, routes/orders.py:172-187
- §3.6 — insert — ambiguity — omitting `colorant_lot_id` for a non-`CLEAR` spec → `ERR_INVALID_REQUEST` — implementation/routes/runs.py:73-76
- §3.6 — insert — ambiguity — zero provisional consumption yields `consumption_variance_pct` 0.00 — implementation/calc.py:174-175
- §3.6 — insert — ambiguity — void with quality lot past `PENDING` → `ERR_INVALID_STATE`; lots re-held/rejected between close and void keep that status and are only credited — implementation/routes/runs.py:304-306, services.py:543-555
- §3.8 — revise — ambiguity — truck planning figures pallet cube/gross weight on a *full* pallet, and pallets-per-truck capacity is floored at one — implementation/calc.py:130-139
- §3.8 — revise — mismatch — shipment persists `pallets`, `volume_cm3`, the three weights, and `freight_cost_cents`; `trucks` is quote/comparison-only (PRD said "persists the full freight computation") — implementation/routes/shipments.py:68-84, services.py:345-361
- §3.8 — insert — ambiguity — `dock_door` outside 1–3 → `ERR_INVALID_REQUEST` — implementation/routes/docks.py:39-40
- §3.8 — insert — ambiguity — dock-appointment list filters by `shipment_id`, `dock_door` (non-integer → 400), or `status` — implementation/routes/docks.py:72-94

**Verification approach:** walked all 19 implementation files (app, auth, envelope, errors, db, util, validate, calc, services, and 14 route modules) endpoint-by-endpoint — state machines, RBAC sets, OCC guards, calculation formulas/rounding, validation order vs the §2.9 pipeline, error ids, response field shapes, cascade side effects, and list filters/ordering. Everything not listed above (endpoint table, role sets, error catalog mapping, purge matrix, AQL bands, freight rounding order, waterfall order, tolerance math, all state-transition tables) was confirmed already pinned and matching.

