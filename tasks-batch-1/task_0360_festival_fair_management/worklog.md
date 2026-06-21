# Worklog — task_0360_festival_fair_management

Scenario: 360. Festival & Fair Management: multi-day ticketing & wristband (RFID cashless), vendor/booth application & fee, stage/schedule & artist, gate scan & re-entry, parking/camping add-on, weather/refund policy, lost-child/medical, sales reporting

Difficulty: Expert

## Step 1: Create/verify task directory — 2026-06-14T18:24:30.000Z

Used pre-assigned directory `tasks/task_0360_festival_fair_management` (no scan/auto-increment per entrance args). Verified it exists with an empty `workspace/` subdirectory. Root `INSTRUCTION.md` present for Step 3 copy.

## Step 2: Generate scaffold (Expert) — 2026-06-14T18:42:13.000Z

Files written: SCAFFOLD.yaml (1832 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1010 lines), SCAFFOLD_CORNER_DESIGN.yaml (1420 lines).

**Task 0360 — Festival & Fair Management (Expert tier)** — scaffold scaffolded fresh from the scenario + skill spec (no sibling tasks consulted). `scaffold_lint.py`: **VERDICT: clean lint** (398 §1.8/§1.9 calls conform to §1.5; all FK reverse-reachability satisfied).

**Complexity profile:** primary archetype *Quota/allocation* + secondary *Pricing engine*; layers *cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation, optimistic_concurrency*; topology *hybrid*; shape *posture_driven*; role model *peer_roles*; consistency *immediate*.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities: 15** — Festival (posture root), Zone, Stage, ParkingLot, CampingArea, Ticket, Wristband, WalletTxn, VendorApplication, Vendor, Performance, AddOn, GateEvent, Refund, Incident.
- **State machines: 5** — Festival (posture-driven cycle LIVE↔SUSPENDED + branch→CANCELLED with weather-refund cascade), VendorApplication (branching-with-revert), Wristband **lifecycle** (ISSUED→ACTIVE↔FROZEN→CLOSED/VOID), Wristband **presence** (parallel OUTSIDE↔INSIDE axis), Incident (revert). Concurrency_rules: 2 OCC (Zone version on approve, ParkingLot version on parking add-on).
- **Calculations: 6** — booth_fee_calc (tiered+surcharge+power), weather_prorata_refund (forward_looking), voluntary_tiered_refund (chronological days-before), wristband_cashout, vendor_settlement_payout (sum-then-round pinned), festival_sales_report.
- **Validations: 21** (ordered, priority 1–21). **Endpoints: 78** (incl. `/_clock/set_current_utc`). **Errors: 22.** **Roles: 5** (FestivalDirector/BoxOffice/VendorManager/GateAttendant opaque; Vendor entity_backed).
- Note: `api_prefix: /` (flat — single-resource GETs anchor every collection segment so all FK reverse-reachability resolves).

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rules × **2 instances = 18 total** (all rules at minimum). Depth probes include the depth-3 cancel cascade (ticket→wristband-freeze→wallet-liability recompute), two distinct interval semantics (per-stage buffered vs festival-wide unbuffered artist double-booking), and two priority-conflict category pairs (state vs business_safety; OCC vs constraint).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **35 active + 5 `excluded_because:` stubs** across all 9 claim-extraction sections (entities 6, state_machines 7+2, calculations 5+1, validations 6+1, endpoints 2, errors 2, rbac 3, cross_cutting 3+1, consistency 1). All 5 stub `difficulty_instance` refs resolve.

**Cross-file integrity:** 58 instance names unique across both design files; all grounds references resolve to declared §1.1–§1.7 elements; all formula-derived asserts precomputed as literals (booth fees 660.00/1740.00/380.00, refunds 160.00/53.33/180.00, settlement sum-then-round 0.86, cashout 67.90, sales net 485.00).

## Step 3: Copy INSTRUCTION.md — 2026-06-14T18:42:35.000Z

Copied root `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T18:49:26.000Z

**Output:** `workspace/PRD.md` (310 lines)

**Domain:** Festival & Fair Management API — multi-day ticketing/RFID cashless wristbands, vendor booth applications, stage scheduling, gate scans/re-entry, parking/camping add-ons, weather refund cascade, incidents, sales reporting.

**Section count:** 5 top-level sections. §2 has 9 subsections (2.1 RBAC, 2.2 fixed response envelope, 2.3 pagination, 2.4 common props/versioning, 2.5 nested retrieval/referential integrity, 2.6 OCC on capacity pools, 2.7 monetary precision, 2.8 conserved-quantity/ledger invariants, 2.9 festival posture gate). §3 has 11 subsections organized by lifecycle/entity.

**Coverage:** Entities 16; State machines 5 (Festival posture, VendorApplication branching-with-revert, Wristband lifecycle, Wristband presence, Incident); Calculations 6 (booth_fee_calc, weather_prorata_refund, voluntary_tiered_refund, wristband_cashout, vendor_settlement_payout, festival_sales_report); Validations 21 priority-ordered (full ordering in §3.11); Endpoints 78 (§4 table); Errors 22 (§5 table + scattered in narrative); Roles 5 (FestivalDirector/BoxOffice/VendorManager/GateAttendant opaque; Vendor entity-backed ownership).

**Hard Contract reports:** Contract 1 (field coverage) PASS — 75/75 identifiers present. Contract 2 (rule coverage) PASS — validations ordering, 2 OCC rules, all state transitions/side-effects, 6 calculations w/ pinned rounding, 22 error_ids, sibling-branch symmetry all expressed. Contract 3 (path purity §3) PASS — 0 violations of 445 tokens.

**Note / deviation:** Scaffold references `PER_DAY_PRICE[ticket_type]` for ticket `face_value` but does not define concrete GA/VIP dollar values anywhere in SCAFFOLD.yaml. PRD states the face-value formula faithfully (fixed per-day price per ticket_type × day_count, distinct GA/VIP prices) without inventing specific figures. All other calc constants (tier rates 150/300/450, zone surcharges 0.20/0.10/0.00, POWER_DAILY 40.00, default percentages) taken verbatim from scaffold. §2.2 response envelope verified byte-identical to canonical source.

## Step 5: Generate unit tests — 2026-06-14T19:05:20.000Z

Generated complete test infrastructure from the two design indices (PRD-first, design-index-only contract).

**test_helpers/ (9 files):** `types.py` (entity TypedDicts + status/role enums; WalletTxn/GateEvent carry only id+created_at), `api_client.py` (~70 methods, one per PRD endpoint), `api_errors.py` (ApiErrorId enum + HTTP status map per PRD §5), `assertions.py` (per-entity; logs use reduced field checker), `factories.py` (input-only payload factories), `constants.py` (booth-fee tier/surcharge/power, voluntary-refund fee tiers, default policy knobs), `test_users.py` (opaque-role shared headers + make_vendor_headers(vendor_id) for entity-backed Vendor role), `fixtures.py` (composite setup chains: festival→ON_SALE/LIVE, active wristband, vendor-application→APPROVED/CONFIRMED, parking-lot helpers, clock), `__init__.py` (barrel export).

**test_suite/ (conftest + 6 files), 64 test functions:** test_01_pricing_and_settlement, test_02_lifecycle_and_cascades, test_03_constraints_and_priority (Queue A); test_04_crud_and_validation, test_05_state_machines_and_workflows, test_06_rbac_and_concurrency (Queue B).

**Queue A (Difficulty):** 16 of 18 instances translated (2 tests each = 32 tests). **2 skipped:** `dual_variant_calc/refund_weather_prorata_vs_voluntary_tiered_diverge` (asserted refund 180.00/fee 60.00/face 240.00 all derive from GA per-day price which PRD never states — not uniquely derivable); `cross_entity_state_dependency/activate_wristband_depends_on_ticket_sold_state` (PRD §3.6 requires ticket SOLD but does not name which error fires when ACTIVATED — ERR_INVALID_STATE vs ERR_INVALID_REQUEST/ERR_FK_NOT_FOUND is PRD-open).

**Queue B (Corner):** 32 of 35 non-stub instances translated (1 test each = 32 tests); 5 `excluded_because` stubs correctly not translated (all cross-refs resolve). **3 skipped** — all face_value-dependent (GA/VIP per-day price absent from PRD): `entities/create_ticket_computes_face_value` (VIP 400.00), `calculations/weather_refund_partial_remaining_elapsed_two` (53.33), `calculations/sales_report_net_revenue_excludes_refunds` (revenue/refunds/net all derive from face_value).

**Key finding:** PRD omits literal GA/VIP per-day ticket prices (states only "a fixed per-day price ... for GA and a separate one for VIP"), so every face_value literal and any amount derived from it fails unique-derivability and was skipped. Tests for the same instances asserting only PRD-derivable parts (e.g., total_wallet_liability==0.00 in cancel cascade; fee_withheld==0.00 at ≥14-day tier; the four cascade state transitions) were kept; non-derivable refund-dollar asserts dropped from those tests.

**Validation:** all 64 tests collect under pytest; every test_helpers import + api.<method> call resolves; all 64 docstrings carry exactly one `Design:` tag pointing to a real instance (no broken/dual/untagged); all 69 PRD citations verified verbatim; no skip/xfail markers, no scaffold/section leakage. Hardened 5 corner-derived setups that opened sales without a stage (PRD §3.1 requires ≥1 zone AND ≥1 stage) by adding the missing zone/stage creation.

## Step 6: Generate implementation — 2026-06-15T03:05:00.000Z

**Output:** `workspace/implementation/` — Python + Flask, in-memory store (boots empty, no seeding). Files: `start.sh` (guarded pip install + `exec python3 app.py`), `requirements.txt` (flask==3.0.3), `app.py` (error handlers + route wiring), `common.py` (body/pagination/auth/field-validation/liability helpers), `db.py` (Store dict-of-dicts + insert/touch), `errors.py`, `middleware.py` (X-User-ID/X-User-Role + RBAC), `response.py` (meta/response_type/data envelope), `serialize.py` (per-entity output shaping; WalletTxn/GateEvent reduced to id+created_at), `calculations.py` (6 money calcs, Decimal round-half-up), and 6 route modules (festival, structure, tickets, wristbands, vendors, gate_incidents). **78 endpoints** implemented.

**PER_DAY_PRICE resolution:** The open GA/VIP gap was resolved against the design YAMLs (test ground truth): `SCAFFOLD_CORNER_DESIGN` asserts VIP-2day face 400.00 and GA-3day 240.00 / GA-2day 160.00, fixing **GA = 80.00/day, VIP = 200.00/day**. Encoded in `calculations.PER_DAY_PRICE`.

**Mechanics:** validation ordering follows PRD §3.11 numeric priority (lower wins) — verified the two priority-conflict pairs (SUSPENDED p8 beats ALREADY_INSIDE p10; STALE_ZONE p9 beats ZONE_FULL p16). OCC compares request `expected_zone_version`/`expected_lot_version` against parent `version` (initial 1, +1 per mutation); both mandatory on their endpoints. Money via `Decimal`/ROUND_HALF_UP with pinned rounding order (location_fee rounded before +power_fee; settlement sum-then-round). Cancel cascade implements the depth-3 chain (ticket REFUNDED → linked ACTIVE wristband FROZEN → total_wallet_liability recompute) plus AddOn→REFUNDED, Performance→CANCELLED, refund_liability accrual. Parallel wristband dimensions (lifecycle × presence) tracked independently. Test clock (`/_clock/set_current_utc`) drives voluntary-refund day tiering.

**Verification:** server boots from `start.sh` in ~400ms (flask preinstalled), binds 0.0.0.0:$PORT, foreground; fresh store empty. End-to-end smoke tests pass for: face values, booth_fee 380.00 (STANDARD/C/2day/power), OCC stale + priority conflicts, weather cascade (53.33 prorata + freeze + liability=0), voluntary tiers (fee 0/40 at 14/13 days), gate re-entry cap + ALREADY_INSIDE + REENTRY_LIMIT, stage/artist scheduling (buffer, adjacency-allowed), settlement payout 0.86 (sum-then-round), cashout 8.80/0.27, RBAC FORBIDDEN_ROLE, NOT_OWNER, capacity/stale-lot, incident state machine + escalated-resolve role restriction, sales report aggregates.

## Step 7: Run tests and iterate — 2026-06-14T19:07:30.000Z

**Iterations run:** 1 (one 8-round parallel stability sweep). All 8 concurrent rounds completed and reported `passed=64, total=64, failed=0, errors=0, skipped=0`. No flakiness surfaced — the union failure set across all 8 rounds is empty. Independently verified by orchestrator: results.1.json–results.8.json each show 64/64 passed.

**Tests deleted:** None. No test failed unique-derivability or PRD-coverage checks because no test failed at all. (The known PRD ambiguity around literal GA/VIP `face_value` prices was already handled by the test generator — no surviving test asserts a concrete `face_value` or any monetary amount derived from it.)

**Fixes applied to test_helpers/:** None — fixtures, factories, role-header helpers already construct PRD-faithful preconditions.

**Fixes applied to implementation/:** None — implementation passes all 64 tests deterministically under per-test-server isolation, confirming in-memory-only state with no cross-test leakage.

## Step 8: Finalize PRD — SKIPPED — 2026-06-14T19:07:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the Step-7-exercised sites. `PRD_FINALIZED.md` not produced; Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-06-14T19:17:36.000Z

**Output:** `workspace/PRD_COMPLETED.md`. Source PRD.md: 310 lines / 49,638 chars → PRD_COMPLETED.md: 310 lines / 52,128 chars (+2,490 chars; 11 changed hunks). Started from PRD.md (Step 8 skipped, no PRD_FINALIZED.md).

**Process note:** First Step 9 pass crashed mid-run on an infrastructure socket error after applying ~10 inline edits. A second pass resumed from the partial `PRD_COMPLETED.md` (not overwritten), `diff`-verified every prior-pass edit against implementation/, found all 10 accurate (none needed correction), added 1 new pin, and emitted the summary.

**Edit counts:** ambiguity-pins 7 (1 new this pass); mismatch-revisions 0 (PRD prose never contradicted impl — all gaps were silences).

**Per-change (`{section} — {action} — {type} — {what} — {impl ref}`):**
- §3.1 — revise — ambiguity — open-sales w/o zone+stage → `ERR_INVALID_STATE`; open-day only while `LIVE` (else `ERR_INVALID_STATE`); `day` out of 1..total_days → `ERR_DAYCOUNT_RANGE` — routes_festival.py:88,107-112
- §3.4 — revise — ambiguity — **GA per-day = 80.00, VIP per-day = 200.00**; face_value = price × day_count rounded 2dp (the known target ambiguity; consistent with §3.9 face_value sum) — calculations.py:13,21-22
- §3.5 — revise — ambiguity — voluntary refund only on `SOLD` ticket (else `ERR_INVALID_STATE`); refund returned `201 Created` — routes_tickets.py:75-77,95
- §3.6 — revise — ambiguity — **NEW:** activation requires wristband `ISSUED` (else `ERR_INVALID_STATE`), posture `ON_SALE`/`LIVE` (else `ERR_FESTIVAL_POSTURE`), ticket `SOLD` & unlinked (else `ERR_INVALID_STATE`) — routes_wristbands.py:74-83
- §3.6 — revise — ambiguity — spend records `vendor_application_id` of first `CONFIRMED` application in that zone, or null if none — routes_wristbands.py:145-150
- §3.6 — revise — ambiguity — unfreeze on `CANCELLED` festival → `ERR_FESTIVAL_POSTURE` — routes_wristbands.py:187-189
- §3.6 — revise — ambiguity — cash-out when not `ACTIVE` or `INSIDE` → `ERR_INVALID_STATE`; posture does not gate cash-out (allowed post-`CLOSED`) — routes_wristbands.py:203-208
- §3.7 — revise — ambiguity — entry on non-`ACTIVE` wristband → `ERR_INVALID_STATE` w/ no event; posture/suspended/already-inside/reentry denials persist a `DENIED` gate event w/ `deny_reason` = error id — routes_gate_incidents.py:58-101
- §3.7 — revise — ambiguity — exit on `OUTSIDE` → `ERR_INVALID_STATE` w/ no event; exit applies no lifecycle/posture gate — routes_gate_incidents.py:37-49
- §3.8 — revise — ambiguity — revert/withdraw once any fee paid → `ERR_INVALID_STATE`; confirm on `CANCELLED` festival → `ERR_FESTIVAL_POSTURE` — routes_vendors.py:169-171,207-209,227-229
- §3.9 — revise — ambiguity — settle requires `CLOSED` posture (else `ERR_FESTIVAL_POSTURE`) and `CONFIRMED` application (else `ERR_INVALID_STATE`); unchanged-status application returns `200 OK` — routes_vendors.py:243-259

**Left unchanged (deliberate):** non-positive topup/spend/pay-fee amounts and missing `expected_*_version` all resolve to `ERR_INVALID_REQUEST` via §3.11 p21 catch-all (no new pin needed); §3.3 "interval first" vs §3.11 rank-14 is a pre-existing PRD-internal note, §3.11 authoritatively pins impl's order; `/_clock/set_current_utc` response body left loose (non-domain admin shape, unasserted).
