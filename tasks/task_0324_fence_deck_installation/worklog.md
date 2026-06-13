# Worklog — task_0324_fence_deck_installation

## Step 1: Create Task Directory — 2026-06-13T05:35:32.000Z

Created pre-allocated directory `tasks/task_0324_fence_deck_installation/` and `workspace/` subdirectory (index pre-assigned; no auto-increment scan performed). Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-06-13T06:07:22.000Z

All three scaffold artifacts are written and the lint verdict is clean. The task directory already had a `worklog.md` and `workspace/` (orchestrator-owned); I left those untouched.

### Summary

Generated the Expert-tier scaffold for **task_0324_fence_deck_installation** (Fence & Deck Installation). All three files written to `tasks/task_0324_fence_deck_installation/`: `SCAFFOLD.yaml` (1353 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1320 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (1194 lines).

**Lint verdict:** `clean lint` — all §1.8/§1.9 calls conform to §1.5; every §1.1 FK has reverse-reachability. 480 calls scanned.

**Complexity profile:** workflow_orchestration (primary) + pricing_engine (secondary); layers: dual-variant calc, cascading side effects, OCC, derived-field reconciliation, rate/threshold triggers; hierarchical topology, branching state shape, peer_roles, immediate consistency.

**Counts:**
- **Entities (12):** Project, Customer, Estimate, LineItem, SiteMeasure, Permit, HoaApproval, MaterialOrder, CrewBooking, ChangeOrder, Draw, Warranty
- **State machines (10):** Project (8-state workflow gate), Estimate, SiteMeasure, Permit (revision cycle), HoaApproval, MaterialOrder, CrewBooking, ChangeOrder (branching fork), Draw, Warranty (claim cycle)
- **Calculations (10):** line_item_estimate (tiered+slope+adder), estimate_rollup (round-per-line tax), reconcile_estimate (dual-variant), draw_schedule (waterfall+cap), draw_rebalance, change_order_reprice (dual-variant basis), material_takeoff (ceil+waste), permit_clearance_derivation, crew_overlap_check (half-open), dock_overlap_check (closed+buffer)
- **Endpoints (46)** — above the 20–32 Expert guideline due to rich multi-stage lifecycle (transition endpoints + mandatory reverse-reachability GETs); `api_prefix` set to `/`.
- **Errors (19)**, **Roles (5):** ProjectManager/Estimator/FieldTech/PermitClerk (opaque) + Customer (entity_backed:Customer), **Concurrency rules (1):** OCC on Project.version for change-order create, **Validations (14)**

**§1.8:** 9 Difficulty Rules × 2 = **18 instances**. **§1.9:** **28 active instances + 2 excluded_because stubs** across all 9 claim-extraction-guide sections (48 unique names total).

All formula-derived assert literals computed in code and verified. Zero unbound `${var}` placeholders. No forbidden concurrency vocabulary; enum-value closure holds for every status field.

## Step 3: Copy Shared Files — 2026-06-13T06:08:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T06:13:04.000Z

All checks pass. The OCC rule fully expresses the write endpoint (change-order creation), the `expected_project_version` field, the version mismatch rejection, and the exact `ERR_STALE_PROJECT_VERSION` at HTTP 412. No fuzzy/approximating words. The §2.2 block is verbatim. Structure is correct (9 §2 subsections, 9 §3 subsections, 4-column endpoint table, 2-column error table). The PRD is complete and all three Hard Contracts pass.

**Generated:** `workspace/PRD.md` — 263 lines, 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue), with 9 §2 subsections and 9 §3 subsections.

**Coverage confirmation:**
- **Entities (11 + Customer):** All 54 distinct field identifiers present (0 missing). `Customer` documented as sole `common_fields: false` entity (only `id`/`created_at`).
- **State machines (10):** All state enumeration values present (0 missing); transitions' from/to states, preconditions+error IDs, and side effects in §3 prose; path-purity verified.
- **Calculations (10):** line_item_estimate (RATE_TABLE, slope 1.12 at ≥15%, ACCESSORY_ADDER), estimate_rollup (round-per-line tax, 9.50/22.00 labor, 650.00 mobilization), reconcile_estimate, draw_schedule (0.20/0.30/0.30/0.20 waterfall, 10000.00 deposit cap strict-greater clamp, FINAL absorbs remainder), draw_rebalance (PAID-locked), change_order_reprice (estimate-basis vs measured-basis), material_takeoff (ceil), permit_clearance_derivation, crew_overlap_check (half-open), dock_overlap_check (closed + 4h buffer) — all precise prose, no pseudocode.
- **OCC:** single rule fully expressed (§2.8 + §3.7).
- **Endpoints:** §4 4-column table covers all scaffold endpoints incl. `/_clock/set_current_utc`.
- **Errors (19):** §5 2-column table; all 19 IDs present, triggers scattered into §2/§3.
- **Validation priority ordering** stated in §2.9.

Hard Contracts 1 (Field-Name Coverage), 2 (Rule Coverage), 3 (§3 Path Purity): all PASS. Neither design YAML was opened or referenced.

## Step 5: Generate Unit Tests — 2026-06-13T06:43:30.000Z

**Stage 1 — `test_helpers/` (9 files written):**
`__init__.py` (barrel export), `types.py` (12 entity TypedDicts + status/role enums; `Customer` correctly omits `version`/`updated_at` as `common_fields:false`), `api_client.py` (one method per endpoint, incl. clock), `api_errors.py` (19 error IDs + HTTP map), `assertions.py` (per-entity assertions + money-invariant checker), `factories.py` (per-entity input-only payload factories), `constants.py` (rate table, accessory adders, labor rates, draw pcts, dock buffer), `test_users.py` (4 opaque role constants + `make_customer_headers()` builder for entity-backed Customer role), `fixtures.py` (composite lifecycle fixtures + change-order/OCC + dual-project scheduling helpers).

**Stage 2 — `test_suite/` (conftest + 9 test files, 64 tests):**
- **Queue A (Difficulty): 36 tests** — all 18 instances covered with ≥2 tests each.
- **Queue B (Corner): 28 tests** — all 28 non-stub instances covered with ≥1 test each.

Every test docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag; all 99 PRD citations verified byte-verbatim against `PRD.md`, zero `...`-fused multi-span quotes, no skip/xfail markers. 64 tests collect cleanly.

**Instances skipped:** None weakened/xfail'd. The 2 `excluded_because` corner stubs (`site_measure_setback_violation_already_covered`, `deposit_cap_clamp_boundary_already_covered`) correctly NOT translated — both cross-refs resolve to real difficulty-design instances that own the assertion.

**One assertion deliberately narrowed (not skipped):** In `material_takeoff_waste_ceiling`, design literal `ceil(200·1.10)=221` is only reachable via IEEE-754 float (`200·1.1=220.00000000000003`); a faithful PRD-only reader using §2.7-mandated decimal arithmetic gets `ceil(220.0)=220`. That value fails unique-derivability, so the test asserts only the basis-independent fence line (`ceil(132·1.10)=146`) and CONFIRMED status. **Flagged as latent PRD/design ambiguity for scaffold author.**

## Step 6: Generate Implementation — 2026-06-13T06:43:30.000Z

**Files written (10, all under `workspace/implementation/`):**
`start.sh` (executable launcher), `requirements.txt` (Flask only), `app.py` (entry point, all routes, error handlers, validation ordering), `db.py` (in-memory dict store + id/timestamp/version helpers), `clock.py` (logical UTC clock via `/_clock/set_current_utc`), `errors.py` (`ApiError` + 19-entry catalogue w/ HTTP codes), `response.py` (PRD §2.2 envelope: `meta`/`response_type`/`data`, `req_` ids, ISO-8601 ms, pagination), `middleware.py` (`X-User-Role`/`X-User-ID` auth + RBAC), `calculations.py` (Decimal/round-half-up pricing engine), `services.py` (derived-field recompute, reconciliation, draw rebalance, permit-clearance derivation, warranty expiry, serialization).

**Endpoints implemented: 46** — all routes from PRD §4 / scaffold §1.5 + `_clock` test hook.

**Verified by live smoke tests:** dual-variant estimated-vs-reconciled (21605.04 → 22266.02), change-order reprice (deltas 1652.44 / 991.46), per-line tax (18.48), slope-15 boundary (4760.00), defaults (4250.00), draw waterfall + deposit cap, full lifecycle to COMPLETED (balance 0.00, ISSUED warranty), clock-driven warranty expiry, OCC version bump + stale rejection (412), cancel cascade, dock 4h-buffer conflict, crew half-open overlap, cancel-restores-slot, validation precedence (401→403→404→422-ref→422-validation→400→412→409→domain) incl. two pinned dual-failure cases.

**Contract confirmation:** start.sh reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec` (pip install guarded); storage in-memory only (plain dicts, no SQLite/JSON/disk); no seeding (fresh boot `total_count: 0`).

## Step 7: Test and Iterate — 2026-06-13T06:49:11.000Z

All 8 parallel rounds are clean (63/63 passing each). Exiting with the summary.

**Iterations run:** 2 (initial diagnostic sweep + one fix, confirmed by a second clean sweep).

**Tests deleted (1):**
- `test_pay_final_draw_before_prior_paid_rejected` (`test_suite/test_08_draws_and_completion.py`) — **STEP 1b ERROR-PRECEDENCE / UNREACHABLE-BRANCH collapse.** PRD §3.8 (line 178) makes FINAL's *invoice* gate require "every prior non-voided draw to be `PAID`," while §3.8 (line 180) requires a draw to be `INVOICED` before it can be paid. Together these foreclose the precondition the test needs: a FINAL draw cannot become `INVOICED` while any prior non-voided draw is still outstanding, so the pay-time `ERR_DRAW_SEQUENCE_VIOLATION` branch is logically unreachable under any PRD-faithful implementation. The test's own setup proved this — it failed at the invoice step with the correct `ERR_DRAW_GATE_NOT_MET`. No PRD-faithful implementation could pass this test, so per the cardinal rules it was deleted rather than weakening the PRD-required invoice gate. This was the scaffold rule `Corner/validations/error_draw_sequence_violation_final_before_prior_paid`, whose own design intent is contradicted by the scaffold's separately-rendered invoice-gate rule.

**Fixes to `test_helpers/`:** none.

**Fixes to `implementation/`:** none. The implementation was faithful to both PRD §3.8 sentences (invoice gate at `app.py:1077-1082` and pay-time sequence check at `app.py:1094-1098`); the lone failure was a test artifact whose setup could not be constructed against the faithful invoice gate.

**Final state:** all 8 parallel rounds clean at 63/63 passing, no flakiness observed across rounds.

## Step 8: Finalize PRD — 2026-06-13T06:51:43.000Z

`PRD_FINALIZED.md` is in place (`workspace/PRD_FINALIZED.md`).

**PRD.md vs PRD_FINALIZED.md:** 263 lines vs 263 lines — **0% delta (byte-identical, `diff` empty)**.

**Changes:** None. No edits were made.

The single `<step_7_diff>` item was a **test deletion** with **zero implementation fixes** and **zero test_helpers fixes**. Verified it is a pure unreachable-branch artifact, not a PRD silence or PRD/impl mismatch:
- **FINAL invoice gate** — PRD §3.8 line 178 ("FINAL requires every prior non-voided draw to be PAID") matches impl `app.py:1077-1082` exactly; uniquely determined.
- **FINAL pay-time sequence gate** — PRD §3.8 line 180 (`ERR_DRAW_SEQUENCE_VIOLATION` only if every non-final non-voided draw already PAID) matches impl `app.py:1095-1098` exactly; uniquely determined.
- Because paying requires `INVOICED` and FINAL reaches `INVOICED` only after the invoice gate passes, the pay-time branch is logically unreachable. Test failed at its own invoice-step setup with the correct `ERR_DRAW_GATE_NOT_MET` — a test-construction impossibility, not a behavioral divergence.

Per instruction not to manufacture edits, the file remains identical to PRD.md. Pre-edit search examined one candidate subject (FINAL invoice-gate vs pay-time-sequence interaction), enumerated impl paths `app.py:1050-1109` + `services.py:42-44/99-104/190-217`, all consistent with existing PRD prose; zero edits committed.

## Step 9: Complete PRD — 2026-06-13T06:57:26.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`, pinning every spot where PRD prose left an interpretation open or contradicted `implementation/`.

**File metrics:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md`: 263 → 263 lines (unchanged); 40,962 → 41,883 chars (+921). 5 changed lines.

**Change counts:** ambiguity-pins: 3, mismatch-revisions: 2.

**Changes:**
- §2.4 Common Resource Properties — revise — mismatch — "A Customer carries only id and created_at" contradicted the response body; clarified it means only system-managed fields, and that input fields `full_name`/`email`/`hoa_governed` are echoed on every read — `app.py:136-143` + `services.py:27-36`.
- §2.9 Validation Ordering — insert — ambiguity — added `project_id` to body-FK resolution (change-order create with unresolved body `project_id` → `ERR_REFERENCE_NOT_FOUND`) — `app.py:847-852`.
- §3.6 Crew Bookings — insert — mismatch — prose labels material-readiness "Second" / crew-collision "Third", but impl evaluates crew-overlap before material-readiness (per §2.9 order) and reports `ERR_CREW_DOUBLE_BOOKED` when both apply; added clarifying sentence pinning evaluation order — `app.py:789-797`.
- §3.7 Change Orders — insert — ambiguity — pinned `new_accessory` to the §3.2 accessory enum domain (out-of-domain → `ERR_INVALID_REQUEST`) — `app.py:869-871`.
- §3.7 Change Orders — revise — ambiguity — pinned the reject `decision` value to `REJECT` (only accepted value, else `ERR_INVALID_REQUEST`); noted withdraw requires no `decision` body — `app.py:1011-1013` (decide), `app.py:1022-1034` (withdraw).

**Deliberately left unchanged** (impl already matches prose, no deviation): draws-list ordering (impl milestone sort coincides with §2.3 `created_at`-asc default since draws created in milestone order); estimate pricing / round-per-line tax / draw waterfall / deposit cap / reconciliation / rebalance; dock-window & crew-window math; permit/HOA clearance derivation & auto-advance; all draw gates incl. FINAL sequence violation; warranty claim/resolve cycle & clock-driven expiry. The `coverage_years` positive-integer check on warranty PATCH is enforced by impl but unexercised by tests and not contradicted by prose — left unpinned to keep the patch minimal (minor residual silence, documented here).

---

## Pipeline Complete

All 9 steps finished. Final state: **63/63 tests passing across all 8 parallel stability rounds.** Deliverables in `tasks/task_0324_fence_deck_installation/`:
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` (Expert tier)
- `workspace/PRD.md` → `workspace/PRD_FINALIZED.md` (identical) → `workspace/PRD_COMPLETED.md` (final contract, +5 pins)
- `test_helpers/` (9 files), `test_suite/` (conftest + 9 test files, 63 tests)
- `workspace/implementation/` (10 files, 46 endpoints, in-memory Flask)
