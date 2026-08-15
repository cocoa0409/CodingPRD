## Step 2: Generate Scaffold — 2026-08-14T13:18:00.000Z

## Task 1743 — Metal Stamping & Progressive Die Plant: scaffold generated

**Files written:**
- SCAFFOLD.yaml
- SCAFFOLD_DIFFICULTY_DESIGN.yaml
- SCAFFOLD_CORNER_DESIGN.yaml

**Counts:**
- Entities: 16 (Customer, Part, Die, Press, PartDieAssignment, SteelCoil, StripLayout, ProductionOrder, DieChangeEvent, ProductionRun, RejectEvent, OutsideProcessingOrder, PPAPSubmission, LayeredAudit, IndexPublication, PriceAdjustment)
- State machines: 9 (Die, SteelCoil, StripLayout, ProductionOrder, DieChangeEvent, ProductionRun, OutsideProcessingOrder, PPAPSubmission, LayeredAudit)
- Calculations: 6 (scrap rate dual-variant, SMED variance per-event vs rolling-average, steel-index price adjustment with pinned rounding order, coil consumption waterfall, heat-lot exposure rollup, reject-count aggregation)
- Validations: 16 (priority-ordered, including two deliberate priority-conflict pairs)
- Endpoints: 77 (including /_clock/set_current_utc test-driving clock with the mandated 2026-08-01T00:00:00Z default)
- Errors: 22
- Roles: 9 (segregation-of-duties role model; PPAP approval and audit recording forbid creator self-disposition)
- Concurrency (OCC) rules: 2 (strip-layout approve on Part.version; run complete on SteelCoil.version — both pass the serial-observability filter)
- §1.8 instances (non-stub): **18** (2 per each of the 9 difficulty rules)
- §1.9 instances (non-stub): **33** (plus 5 excluded_because stubs pointing at §1.8 instances)

**Difficulty highlights (pushed past expert per request):** dual-variant calcs in two different entity domains (order pricing vs run quality); combinatorial formulas in modes (b) nested-rounding-order and (a) multi-input windowed aggregation; non-linear machines on different entities (PPAP rejection-resubmission cycle, order IN_PROGRESS→RELEASED revert); a depth-4 heat-lot quarantine cascade (audit FAIL → coil QUARANTINED → run ABORTED → order reverts) plus a depth-2 run-completion ledger cascade; boundary checks at exact coil depletion (== 0 vs 0.001) and exact ordered quantity (>= 50 vs 49); two interval semantics (half-open runs vs 30-minute teardown-buffered changeovers); two compensating invariants over different conserved quantities (coil kilograms, die lifetime shots).

**Lint verdict (verbatim):** VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

## Step 3: Copy Shared Files — 2026-08-14T13:19:21.000Z

Copied INSTRUCTION.md to tasks/task_1743_metal_stamping_progressive_die_plant/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T13:37:45.000Z

**Output:** workspace/PRD.md — 350 lines, 8,072 words.

**Withheld-file constraint honored:** SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened, grepped, or referenced.

### Section list
- **§1 Introduction** — 2 paragraphs, business-context angle
- **§2 Global Specifications** (10 subsections): 2.1 RBAC (all 9 roles with opaque-identity prose), 2.2 API Response Structure (byte-identical to section-2.2-response-structure.md, verified), 2.3 Pagination (limit default 10, min 1, max 100, offset 0, created_at ascending, meta fields), 2.4 Logical Clock & Common Resource Properties (default 2026-08-01T00:00:00Z, append-only RejectEvent/IndexPublication/PriceAdjustment carry only id+created_at), 2.5 Validation Pipeline (all 16 validations in explicit priority order), 2.6 Hierarchical Retrieval & filter listings, 2.7 Units/Precision (3-decimal weights, 6-decimal scrap rates round-once, integer cents, whole-minute SMED with 2-decimal rolling average), 2.8 OCC, 2.9 Conserved Coil Ledger & heat-lot traceability, 2.10 Press time discipline (half-open windows, 30-minute teardown buffer)
- **§3 Business Logic** (10 subsections): 3.1 Customers & index publications, 3.2 Parts & strip layouts (OCC-gated supersede), 3.3 Dies/presses/pairing/repair/retire, 3.4 Coil receiving & exposure read, 3.5 PPAP cycle & release gates, 3.6 Changeovers & SMED performance, 3.7 Runs: scheduling/sensing/settlement/scrap rates/aborts, 3.8 Outside processing & close-short, 3.9 Layered audits & tier-3 quarantine cascade, 3.10 Close-out & index-linked price adjustment (pinned 5-step formula, both variants, 1-cent floor)
- **§4 Endpoint Definitions** — 77 endpoints, 4 columns only (Method, Path, Description, Authorized Role(s))
- **§5 Error Code Catalogue** — 22 errors, 2 columns only (no trigger conditions)

### Hard Contract Reports
Field coverage check: 97 required, 97 present, 0 missing — PASS
Rule coverage check: validations 16/16; OCC rejections 2/2 (+1 endpoint-declared expected_order_version); state transitions 38/38; calculations 6/6; error IDs 22/22; side_effects/applies_to all expressed; entity field structured content reconstructible; sibling-branch symmetry 0 asymmetric — PASS
Path purity check (§3 only): 474 backtick tokens scanned, 0 path tokens, 0 bare HTTP-method tokens, 0 method+path combined — PASS

One interpretation note: the release endpoint's input declares expected_order_version ("OCC: required") despite having no concurrency_rules entry. The PRD covers it as a third OCC write with the catalog's generic ERR_STALE_VERSION (412) rejection — the only self-consistent lossless reading of the scaffold.

## Step 5: Generate Unit Tests — 2026-08-14T14:21:56.000Z

Generation complete for task_1743_metal_stamping_progressive_die_plant.

**Tests emitted: 69 total**
- **Queue A (Difficulty): 36 tests** — all 18 instances covered at exactly 2 tests each (dual_variant_calc ×2 instances, combinatorial_formula ×2, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair_validation_conflict ×2, boundary_precision_check ×2, cross_entity_state_dependency ×2, resource_temporal_overlap ×2, compensating_invariant ×2).
- **Queue B (Corner): 33 tests** — 31 of 32 non-stub instances covered (ppap_level_mismatch_rejected gets 2 tests: level mismatch + missing control plan). All 5 excluded_because: stubs left untranslated; their cross-references verified to resolve to real §1.8 instances.

**Instances skipped: 1**
- Corner/calculations/heat_lot_exposure_rollup_sums_remaining — **non-uniquely-derivable**: PRD §3.4 describes the exposure sum in prose but never names the response field (exposure_kg has zero verbatim PRD hits), so no assertion target exists that two PRD-only readers would both implement.

**PRD-silent assertion branches dropped within emitted instances** (instances still covered via their PRD-derivable assertions): scrap-rate numerics (standard_scrap_rate/actual_scrap_rate/scrap_variance unnamed in PRD) on the dual-variant scrap instance; the rolling_average_variance field on the SMED read (unnamed in PRD — per-event variance_minutes, which PRD names, is asserted instead); the rejection_reason echo in the PPAP cycle; version == 1 at creation (initial version value unpinned).

**One recipe-direction correction**: changeover_teardown_buffer_overlap was translated in the PRD-derivable direction — a *changeover creation* whose 30-minute teardown-extended window overlaps an existing SCHEDULED run or PLANNED changeover is rejected with ERR_CHANGEOVER_CONFLICT (PRD §2.10/§3.6). The recipe's literal trigger (run creation rejected with ERR_CHANGEOVER_CONFLICT) contradicts §2.10, which limits run-creation checks to runs only.

**Fixture robustness adjustments** (asserted values unchanged): order quantities lowered in two recipes (coil_depletion 200→100, immediate_consistency 500→100) so run scheduling satisfies the §3.7 coil-sufficiency estimate under every plausible reading of "planned good-part quantity".

**test_helpers written (9 files)**: types.py (16 entity TypedDicts, append-only trio correctly omit version/updated_at), api_client.py (60 endpoint methods), api_errors.py (22 errors registered with framework), assertions.py, factories.py (auto-unique codes), constants.py, test_users.py (9 opaque roles + SoD user-id builders), fixtures.py (layered plant bring-up: part-ready → released order → die-installed press → approved coil → running/completed run → completed order, tier-3 quarantine trigger).

**test_suite written**: conftest.py + 7 files (test_01 master data/RBAC, test_02 layouts/PPAP/release gates, test_03 coil disposition/ledger, test_04 dies/changeovers/SMED, test_05 runs/settlement, test_06 orders/pricing, test_07 audits/quarantine cascade).

**Verification**: 69/69 tests collect; every test docstring carries PRD citations of which all 95 quoted lines survive literal whitespace-normalized grep of PRD.md; every docstring ends with exactly one resolving Design: tag; no skip/xfail markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T14:21:56.000Z

Implementation complete and verified. Summary:

## Files written
All under workspace/implementation/:

- **start.sh** (executable) — guarded dependency install (pip install only if import flask fails, so per-test reboots are no-ops), then exec python3 app.py in the foreground.
- **requirements.txt** — flask>=3.0.
- **app.py** — Flask entry point, error handlers, all 62 PRD endpoint-table routes (77 method+path route decorators — every PRD §4 row), serializers, and all business logic.
- **db.py** — 16 in-memory dicts keyed by id; starts empty, no seeding anywhere.
- **errors.py** — ApiError class + all 22 catalog error IDs with exact HTTP statuses.
- **middleware.py** — X-User-ID/X-User-Role extraction, 9-role validation (401 ERR_UNAUTHENTICATED), per-endpoint role enforcement (403 ERR_UNAUTHORIZED).
- **util.py** — logical clock (boots at exactly 2026-08-01T00:00:00Z, never wall-clock), ISO-8601 timestamps with 3 fractional digits, req_ IDs, response envelope (meta.api_request_id/api_request_timestamp + response_type + data; pagination fields limit/offset/total_count/has_more in meta), Decimal-based round-half-up helpers (3/6/2/0 decimals), common-field and ledger-field factories.

## Endpoint count
**62 endpoints** from the PRD §4 table (77 route registrations counting method+path pairs — exact 1:1 match with the table, verified by diff), including the logical-clock endpoint, all CRUD, all action endpoints, both computed reads (/api/presses/{id}/smed-performance, /api/heat-lots/{heat_lot_number}/exposure), and all reverse-reachability filtered list endpoints.

## State machines implemented (8)
Die (AVAILABLE/ASSIGNED/IN_REPAIR/RETIRED with repair-threshold gates, run-abort cascade on repair pull, assignment deletion on retire), SteelCoil (RECEIVED/APPROVED/ON_HOLD/REJECTED/QUARANTINED/DEPLETED incl. auto-DEPLETED at exactly 0 and the tier-3 heat-lot quarantine cascade), StripLayout (DRAFT/APPROVED/SUPERSEDED with OCC-gated supersede and Part.steel_content_kg sync), ProductionOrder (OPEN/RELEASED/IN_PROGRESS/COMPLETED/CLOSED/CANCELLED with auto-revert to RELEASED), DieChangeEvent (PLANNED/IN_PROGRESS/COMPLETED/CANCELLED with 30-minute teardown-buffer conflict checks), ProductionRun (SCHEDULED/RUNNING/COMPLETED/ABORTED), OutsideProcessingOrder (SENT/PARTIAL_RETURN/CLOSED with return caps and close-short), PPAPSubmission (SUBMITTED/UNDER_REVIEW/APPROVED/REJECTED with resubmission revision counter), plus LayeredAudit PENDING/PASS/FAIL with tier escalation and tier-3 cascade.

## Calculations implemented
- **steel_index_price_adjustment** — pinned order: delta → pass-through → material term → round-half-up whole cents *before* addition → floor ≥1 cent (ERR_PRICE_FLOOR_BREACH); both RELEASE_LOCKED and SHIPMENT_SPOT variants with published_at DESC / created_at ASC tie-break.
- **scrap rates** — exact-rational standard vs sensed actual, rounded once to 6 decimals half-up; zero-shots and rejects-exceed-shots guards.
- **smed_variance** — floor-truncated whole minutes per event; rolling average over last N=min(10, count) COMPLETED events (actual_end DESC, created_at ASC), 2 decimals half-up.
- **coil_consumption_reconciliation** — conserved ledger, 3-decimal half-up, negative → ERR_COIL_WEIGHT_EXCEEDED, exact-zero → DEPLETED.
- **heat_lot_exposure_rollup** — 3-decimal kg sum over APPROVED/ON_HOLD/QUARANTINED coils plus distinct affected orders.
- **reject_count_aggregation** — per-run sum, no cross-run leakage.

Also implemented: the three OCC rules (expected_part_version, expected_coil_version, expected_order_version → 412 ERR_STALE_VERSION), the 16-step validation pipeline ordering, segregation of duties on PPAP/audit disposition, and half-open run-window plus 30-min-buffered changeover overlap checks.

## start.sh contract satisfaction
- **PORT env**: app.py reads int(os.environ.get("PORT", "10000")).
- **0.0.0.0 bind**: app.run(host="0.0.0.0", ...).
- **Foreground**: exec python3 app.py replaces the shell; signals propagate.
- **Fast reboot**: install guarded by python3 -c "import flask" so per-test-server restarts skip pip.

Verified by smoke tests: fresh start.sh boot → empty store (total_count: 0) and clock at 2026-08-01T00:00:00.000Z; a 49-assertion end-to-end suite covering the full coil-to-invoice chain passed with zero failures.

## Step 7: Run Tests and Iterate — 2026-08-14T14:26:02.000Z

All 8 parallel rounds passed clean: **69/69 tests in every round, 0 failures, 0 errors, 0 skipped**.

- **Iterations run**: 1 (the initial 8-round parallel sweep came back clean on first pass)
- **Tests deleted**: none
- **Fixes applied to test_helpers/**: none
- **Fixes applied to test_suite/**: none
- **Fixes applied to implementation/**: none

The implementation in workspace/implementation/ and the test artifacts in test_suite/ + test_helpers/ are fully stable across all 8 concurrent rounds — no flakiness, no timing-sensitive bugs surfaced, no PRD-coverage gaps to triage. The benchmark contract is satisfied: all tests trace to PRD prose and the implementation passes them deterministically. (Orchestrator verification: all 8 results.{1..8}.json files independently show passed=69 total=69.)

## Step 8: Finalize PRD — 2026-08-14T14:26:02.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — zero iterations beyond the baseline. Per the skip condition, PRD.md already determines every behavior the implementation exhibits; no PRD_FINALIZED.md is produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-08-14T14:55:53.000Z

All edits verified — pipeline renumbering is internally consistent, no stale references to the removed per-order aggregation or the old "audit window" phrase remain. The file is complete.

**Source vs output:** PRD.md = 350 lines / 57,228 chars → PRD_COMPLETED.md = 354 lines / 65,075 chars (**+7,847 chars**, all in-paragraph inserts/revisions; no new sections).

**Counts:** 40 ambiguity-pins, 8 mismatch-revisions (48 change sites total).

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.1 — revise — mismatch — CostAnalyst read scope now includes parts (GET /api/parts authorizes CostAnalyst) — app.py:539,554
- §2.2 — insert — ambiguity — undefined routes / unsupported methods return standard envelope with ERR_NOT_FOUND (404) — app.py:72-79
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → ERR_INVALID_REQUEST (400) — util.py:105-128
- §2.3 — insert — ambiguity — created_at ties broken by creation order; index-publications listing ordered by creation order, never published_at — app.py:424
- §2.3 — insert — ambiguity — has_more = (offset + returned items) < total_count — util.py:82
- §2.4 — insert — ambiguity — clock-set accepts any valid ISO instant, no monotonicity enforcement — app.py:385-392
- §2.4 — insert — ambiguity — version starts at 1 at creation — util.py:236-243
- §2.4 — insert — ambiguity — client datetimes normalized to UTC (offset-less read as UTC), stored at 3 fractional digits, sub-ms truncated — util.py:44-59
- §2.5 check 3 — insert — ambiguity — body-referenced ids existence-checked after required-field presence, before remaining checks, in narrative order — app.py:1465-1470
- §2.5 check 5 — revise — mismatch — quality gates are exactly: quarantined/held/rejected coil blocks run start; die at/beyond threshold blocks die-change start and run start only; never at scheduling/planning — app.py:1394, 1556-1561
- §2.5 items 9/13 — revise — mismatch — coil-weight sufficiency now precedes run-window overlap (run_create checks weight first) — app.py:1483-1491
- §2.5 items 15/16 — revise — mismatch — field shape now precedes uniqueness (all creates validate shapes before duplicate scans); boolean-fields rule added — app.py:443-451
- §2.5 closing — revise — mismatch — replaced "business always beats field shape" with actual interleaving: action endpoints run state+SoD before body shape; creation endpoints run presence → body-ref existence → shape → business; uniqueness last — app.py:1596-1620, 508-521
- §2.6 — insert — ambiguity — filters exact-equality with empty-page on no match; audit_tier filter non-integer → 400; customers active filter = case-insensitive "true", else inactive — app.py:471-474, 799-805, 1935-1940
- §2.7 — insert — ambiguity — per-field JSON integer vs decimal typing; integral decimals may serialize without decimal point — util.py:220-226, app.py as_int/as_number sites
- §2.8 — insert — ambiguity — missing/non-integer expected-version → 400; integer mismatch → 412; OCC pipeline position pinned (after state precondition + version-field shape, before business gates; run completion follows §3.7's pinned order) — app.py:1052-1059, 1133-1139, 1598-1620
- §3.1 — insert — ambiguity — base_index_value and value_usd_per_ton must be non-negative — app.py:442, 402
- §3.1 — insert — ambiguity — index selection yields null when no publication stands at/before the reference instant — app.py:349-368
- §3.2 — insert — ambiguity — part: thickness_mm > 0, net_weight_kg ≥ 0, base_piece_price_cents integer ≥ 1 — app.py:513-515
- §3.2 — insert — ambiguity — layout: strip_width_mm/pitch_mm/gross_weight_per_part_kg > 0, parts_per_strip_segment integer ≥ 1 — app.py:1021-1024
- §3.3 — insert — ambiguity — die rated_tonnage/min_bed_width_mm/repair_threshold_shots and press tonnage/bed_width_mm/strokes_per_min are integers ≥ 1 — app.py:611-614, 717-719
- §3.3 — insert — ambiguity — repair-pull aborts do not trigger §3.5 order reversion; IN_PROGRESS order left without active runs stays IN_PROGRESS — app.py:656-660 (no _maybe_revert_order)
- §3.4 — insert — ambiguity — coil thickness_mm/received_weight_kg > 0; received weight rounded to 3-dp half up at receipt — app.py:895-907
- §3.4 — insert — ambiguity — exposure read returns heat_lot_number / exposure_kg / affected_order_ids (sorted ascending); unknown heat lot → 0 and [] — app.py:1002-1006
- §3.5 — insert — ambiguity — resubmission precondition → ERR_INVALID_STATE (409), evaluated after the two level rules — app.py:1812-1824
- §3.5 — insert — ambiguity — steel_index_at_release null until release; captured as null when no publication qualifies — app.py:1158-1159
- §3.5 — revise — mismatch — order reversion scoped to operator aborts and heat-lot cascade; die-repair pull explicitly does not revert — app.py:1222-1231 vs 656-660
- §3.5 — insert — ambiguity — cancelling while a run is RUNNING → ERR_INVALID_STATE (409) — app.py:1240-1242
- §2.10 — revise — ambiguity — changeover overlap compares new extended window against existing changeovers' likewise-extended windows; all comparisons half-open (touching endpoints don't conflict) — app.py:1300-1335
- §3.6 — insert — ambiguity — smed_target_minutes is a non-negative integer — app.py:1321
- §3.6 — insert — ambiguity — changeover start does not disturb a run underway on the press — app.py:1399-1408
- §3.6 — revise — ambiguity — removed die returns to AVAILABLE only when still ASSIGNED at completion — app.py:1427-1431
- §3.6 — insert — ambiguity — SMED read returns press_id / events_considered / average_variance_minutes; no completed events → 0 and 0 — app.py:823-834
- §3.7 — revise — ambiguity — estimated consumption pinned: (quantity_ordered − quantity_produced_good) when positive else full quantity_ordered, × steel_content_kg, 3-dp half up; scheduling consults neither die threshold nor coil disposition — app.py:1452-1458, 1483-1485
- §3.7 — insert — ambiguity — standard scrap rate computed/stored at run start from then-APPROVED layout, visible while RUNNING — app.py:1576-1587
- §3.7 — insert — ambiguity — reject station_number integer ≥ 1 — app.py:1701
- §3.7 — insert — ambiguity — shots_recorded non-negative integer; negative → 400 — app.py:1600-1604
- §3.7 — revise — mismatch — standard rate recomputed at completion from part's then-current steel_content_kg (not frozen to start-time layout); variance = rounded actual − rounded standard, rounded again; no per-order aggregation — app.py:1631-1640
- §3.7 — revise — ambiguity — abort preserves counters as they stand; good_count only written at completion so aborted runs keep good_count 0 — app.py:1659-1667
- §3.8 — insert — ambiguity — outside-order creation does not consult parent order status — app.py:1724-1742
- §3.8 — insert — ambiguity — return quantities are non-negative integers — app.py:1760-1761
- §3.8 — insert — ambiguity — shortage_acknowledgment must be non-empty string, validated before the parent-COMPLETED check — app.py:1782-1789
- §3.9 — insert — ambiguity — audit_tier outside 1/2/3 → 400; findings_count non-negative integer — app.py:1906-1908, 1983
- §3.9 — insert — ambiguity — escalated audit's scheduled_date stamped with logical clock at escalation; system-created with no creator, SoD never blocks its recording — app.py:1993-2003
- §3.9 — revise — ambiguity — tier-3 cascade implicates heat lots of all COMPLETED/RUNNING runs on the press, no time-window restriction — app.py:2009-2016
- §3.10 — revise — mismatch — order completion computes no per-order scrap aggregate — app.py:1165-1178
- §3.10 — insert — ambiguity — close responds with the updated order object; adjustment read via the price-adjustments listing — app.py:1219
- §3.10 — insert — ambiguity — null index selection falls back to customer's base_index_value (delta zero) for both variants — app.py:1197-1198

**Key findings:** the most substantive misalignments were (1) the §2.5 pipeline order itself — impl checks coil-weight before run-overlap and field-shape before uniqueness, so items 9/13 and 15/16 were swapped and the closing "business always beats shape" claim rewritten to describe the actual interleaving; (2) §3.5's blanket order-reversion rule vs impl's die-repair pull never reverting (app.py:656-660 lacks the _maybe_revert_order call that all other abort paths make); (3) §3.7/§3.10's claimed per-order scrap aggregation, which impl never computes; and (4) the standard scrap rate, which impl recomputes at completion from the part's *current* steel_content rather than freezing the start-time layout's geometry.
