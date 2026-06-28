# Worklog — task_0626_mobile_phlebotomy

## Step 1: Create Task Directory — 2026-06-22T11:33:00.000Z

Created `./tasks/task_0626_mobile_phlebotomy/workspace` (pre-assigned task directory, index NOT auto-computed per concurrency constraint). Difficulty band: Expert.

## Step 2: Generate Scaffold — 2026-06-22T12:02:00.000Z

There's a `worklog.md` and `workspace/` that pre-existed (not created by me — likely scaffolded by the directory setup). My three required files are all present. I generated the scaffold purely from the scenario description and the skill specification, without reading any sibling task directory.

## Summary

Generated all three scaffold artifacts for **task_0626_mobile_phlebotomy** (Getlabs-style Mobile Phlebotomy & At-Home Lab Draw) at the **Expert** difficulty band. All files pass `scaffold_lint.py` with `VERDICT: clean lint` (614 calls scanned, all conform; all 12 FKs reverse-reachable).

**SCAFFOLD.yaml** (§1.0–§1.7):
- **Complexity profile**: workflow_orchestration + temporal_windowing; hybrid topology; branching state machines; peer_roles; layers = cascading side effects, dual-variant calc, OCC, derived-field reconciliation. `api_prefix: ""` (flat topology with many top-level collections).
- **12 entities**: TestPanel, LabPartner, Phlebotomist, RouteDay, LabOrder, Appointment, DrawKit, Specimen, ChainOfCustodyEvent (append-only, common_fields:false, self-referential `prior_event_id`), CourierManifest, LabResult, Invoice.
- **5 state machines**: LabOrder (branches DRAW_COMPLETED → {RESULTED | REDRAW_REQUIRED}), Appointment (DISPATCHED→SCHEDULED revert), Specimen (MANIFESTED → {ACCESSIONED | QNS_REJECTED}), CourierManifest, Invoice.
- **7 calculations**: self-pay vs insurance invoice totals (dual-variant), order_total_due_estimate (estimate-vs-final on LabOrder), phlebotomist_redraw_strike, route_day_booked_stop_count, manifest_accession_due (SLA), order_specimens_accessioned_count.
- **16 validations** (priority-ordered, incl. two distinct temporal-overlap rules: half-open appointment windows vs closed-interval route-day shifts), **53 endpoints** (incl. `POST /_clock/set_current_utc` defaulting to 2026-01-01T00:00:00Z), **45 errors**, **5 roles** (OrderingProvider, Dispatcher, Phlebotomist [entity_backed], LabOps, BillingAgent), **1 concurrency rule** (OCC on RouteDay.version at booking, 412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rule_ids × 2 = **18 instances**, each with executable setup_api_calls chains. All formula-derived asserts pre-computed as literals and verified by code.

**SCAFFOLD_CORNER_DESIGN.yaml**: **40 corner instances** across all 9 claim-extraction-guide sections (35 active + 5 `excluded_because:` stubs citing valid §1.8 instances).

## Step 3: Copy Shared Files — 2026-06-22T12:04:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0626_mobile_phlebotomy/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T12:07:00.000Z

Generated `workspace/PRD.md` from the mobile-phlebotomy scaffold.

**Document metrics:**
- **5 top-level sections** (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue)
- **20 subsections** — §2 has 9 domain-derived cross-cutting subsections (RBAC, response structure, pagination, common properties + logical clock, hierarchical consistency/cascades, nested retrieval, validation ordering, OCC, monetary precision); §3 has 11 lifecycle/workflow subsections
- **306 lines**
- §4 endpoint table: exactly 4 columns, all 53 scaffold endpoints
- §5 error table: exactly 2 columns, all 45 scaffold error codes

**Hard contract results (transcript-only, per spec):**
- **Contract 1 (Field-Name Coverage): PASS** — all 60 required identifiers appear verbatim in backticks.
- **Contract 2 (Rule Coverage): PASS** — all 45 error IDs, all 32 state/enum values, all 4 custody event_type values, and all billing constants surface in §2/§3 prose.
- **Contract 3 (§3 Path Purity): PASS** — 387 §3 backtick tokens scanned, zero path-leading, zero bare-method, zero method+path tokens.

**Constraint confirmation:** Did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml, and did not read any sibling task directory.

## Step 5: Generate Unit Tests — 2026-06-22T12:28:00.000Z

Generated complete test infrastructure for **task_0626_mobile_phlebotomy** (Expert band).

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — entity TypedDicts + status/role enums; `ChainOfCustodyEvent` correctly omits `version`/`updated_at` (append-only, `common_fields: false`).
- `api_client.py` — one method per PRD endpoint (incl. `/_clock/set_current_utc`, custody-events, lab-results).
- `api_errors.py` — all 44 error IDs + HTTP status map.
- `assertions.py`, `factories.py`, `constants.py` — per-entity assertions, input-only payload factories, billing/strike constants.
- `test_users.py` — opaque-role shared headers + `make_phlebotomist_headers(id)` (Phlebotomist sole entity-backed role).
- `fixtures.py` — composite lifecycle helpers (scheduled → draw-completed → in-transit-manifest → resulted, redraw-then-resulted, 3-strike suspension).

### Stage 2 — `test_suite/` (conftest + 7 test files, 71 tests)
- **Queue A (Difficulty): 36 tests** — all **18 instances** across 9 rules, each with **exactly 2 tests**.
- **Queue B (Corner): 35 tests** — all **35 non-stub instances**, each with **exactly 1 test**.

### Audits passed
- All **97 PRD citations verbatim-match** PRD.md.
- Every test has **exactly one** Design tag; no skip/xfail; no scaffold/table references.
- **5 corner stubs** (`excluded_because:`) correctly not translated; all 5 cross-references resolve to real difficulty instances.

### Instances skipped
**None.** All 18 difficulty instances and all 35 non-stub corner instances passed the PRD-first two-condition filter.

## Step 6: Generate Implementation — 2026-06-22T12:28:00.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

### Files (23 total)
- `start.sh` (foreground launcher, guarded pip, `exec python3 app.py`), `requirements.txt` (Flask 3.0.3)
- `app.py` (reads `$PORT` default 10000, binds `0.0.0.0`), `db.py` (in-memory `Store`, 12 dicts), `clock.py` (logical server clock, default `2026-01-01T00:00:00Z`)
- `errors.py`, `response.py`, `middleware.py` (RBAC), `common.py`, `serializers.py`
- `services/billing.py`, `services/cascade.py` (redraw cascade, route-day decrement, strike/suspension threshold 3, manifest auto-delivery), `services/custody.py` (append-only chain)
- `routes/` — catalog, field, orders, appointments, specimens, manifests, results, invoices, clock_route

### Endpoints: 53 (52 functional + `/_clock/set_current_utc`)

### Constraints confirmed
- **Storage 100% in-memory**, nothing seeded at startup (verified: 0 entities after fresh boot).
- **start.sh** reads `$PORT`, binds `0.0.0.0`, runs foreground via `exec`.

### Note
PRD's `GET /lab-results/{id}` has no dedicated `ERR_LAB_RESULT_NOT_FOUND`; that path returns closest resource-scoped 404 (`ERR_ORDER_NOT_FOUND`) — documented inline in `routes/results.py`. (Flag for Step 7 diagnostic.)

## Step 7: Run Tests and Iterate — 2026-06-22T12:31:00.000Z

## Summary

The task `task_0626_mobile_phlebotomy` is already in a fully-passing, stable state. The first 8-round parallel stability sweep passed cleanly with no diagnostic action required.

**Iterations run:** 1 (one full 8-round parallel sweep).

**Sweep result:** All 8 concurrent rounds passed 71/71 tests each — 0 failed, 0 errors, 0 skipped, 0 flakiness. Each round restarted the server via `start.sh` before every test (`per-test-server` isolation); round wall time ~108s, all 8 ran concurrently without port collisions.

**Tests deleted:** None. Every test traces to a verbatim PRD sentence (each carries an inline `PRD §X.Y: "..."` quote) and uniquely determines its assertion. I reviewed all 7 test files against the diagnostic protocol — coverage, unique-derivability, and test-vs-PRD consistency all hold (e.g. validation-ordering precedence tests, OCC stale-version-before-business-checks, half-open vs closed-interval overlap semantics, the redraw cascade's four hops, both billing variants with capped waivers, and the clock-stamped `accession_due_utc` with three fractional digits).

**Fixes applied to test_helpers/:** None needed. The fixtures correctly use `make_phlebotomist_headers(phleb_id)` with the real Phlebotomist entity id for ownership-gated on-site actions and shared opaque-operator constants for the other four roles, consistent with PRD §2.1.

**Fixes applied to implementation/:** None needed. The implementation (in-memory `Store`, no seeding, logical clock starting at `2026-01-01T00:00:00Z`, billing/cascade/custody services) already satisfies every PRD-derived assertion.

Scratch `results.*.json` files were removed after verification. No code, test, or helper changes were required.

## Step 8: Finalize PRD — SKIPPED — 2026-06-22T12:31:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. PRD_FINALIZED.md NOT produced; Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-06-22T12:38:00.000Z

Produced `workspace/PRD_COMPLETED.md` from PRD.md (no PRD_FINALIZED.md since Step 8 skipped).

**File line/char counts:** PRD.md = 306 lines / 44,763 chars; PRD_COMPLETED.md = 306 lines / 45,916 chars; char delta = **+1,153**.

**Counts:** ambiguity-pins = **5**; mismatch-revisions = **0**. (Implementation contained no behavior that contradicted existing PRD prose — every gap was PRD silence.)

**Per-change log:**
- §2.3 Pagination — insert — ambiguity — pinned out-of-range clamping (limit → [1,100], negative offset → 0, absent/empty/non-integer → default) and `created_at` tie-break by ascending `id` — common.py:119-138, 148-150.
- §2.3 Pagination — insert — ambiguity — defined `total_count` (full filtered set pre-pagination) and `has_more` (`offset + page_len < total_count`) — response.py:49-55, common.py:141-145.
- §2.4 Common Resource Properties — insert — ambiguity — pinned `version` initial value `1`; `created_at`/`updated_at` stamped from wall-clock (not logical clock) — db.py:39-51, response.py:22-27.
- §2.6 Nested Resource Retrieval — insert — ambiguity — pinned no lab-result-specific not-found error; missing lab result returns `ERR_ORDER_NOT_FOUND` — routes/results.py:17-20.
- §3.6 On-Site Collection — insert — ambiguity — pinned specimen collection not gated by appointment status or phlebotomist identity (only `Phlebotomist` role + tube-label uniqueness) — routes/appointments.py:125-153.

**Items left unchanged (verified consistent):** manifest specimen_count reflection, dispatch check ordering, billing formulas, redraw cascade strike threshold `>=3`, window/shift interval semantics, manifest auto-deliver, set_current_utc empty-object response. `ERR_KIT_NOT_FOUND` defined but unreachable (consistent with PRD listing it without demanding behavior).

---

## Pipeline Complete

All 9 steps finished. Final state: **71/71 tests passing across all 8 concurrent stability rounds**, zero fixes/deletions required. Task directory is complete with SCAFFOLD (×3), PRD.md, PRD_COMPLETED.md, test_helpers/, test_suite/, and workspace/implementation/.
