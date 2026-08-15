# Worklog — task_1628_tenant_improvement_project_management

## Step 1: Create Task Directory — 2026-08-14T03:15:49.000Z

Directory `tasks/task_1628_tenant_improvement_project_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T04:25:15.000Z

All three artifacts are written and the lint is clean. Note: a `worklog.md` and `workspace/` directory already existed in the task directory (created outside my session — I did not touch them, per the no-peek constraint).

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1628_tenant_improvement_project_management/`):
- `SCAFFOLD.yaml` (§1.0–§1.7; 109 KB) — no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (151 KB) — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` (163 KB) — single top-level `scaffold_corner_design:`

**Counts:**
- Entities: **16** (Property, LeaseSpace, Tenant, Lease, TIProject, WorkLetter, PlanSubmission, PlanReviewComment, Contractor, ContractorEngagement, ScheduleMilestone, ChangeOrder, DisbursementRequest, LienWaiver, PunchItem, OverageInvoice)
- State machines: **14** — 5 cyclic/branching (WorkLetter negotiation loop PROPOSED↔COUNTERED, PlanSubmission revision-supersede cycle, ContractorEngagement suspend/reinstate, PunchItem RESOLVED→OPEN reopen loop, OverageInvoice ISSUED↔DISPUTED), plus a 9-phase gated TIProject master machine with per-state enumerated cancel cascades
- Endpoints: **102** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- Errors: **31**; Validations: **32** ordered priorities (auth→existence→shape→state→safety→constraint→temporal→referential→fiscal→OCC)
- §1.8 instances: **19 non-stub** (9 rules; combinatorial_formula has 3 — one per mode (a) tiered retainage, (b) per-line CO rounding pinned to round-per-line-then-sum, (c) pinned evaluation order for the headroom/overage circular dependency)
- §1.9 instances: **41 non-stub + 7 excluded_because stubs** across all 9 guide sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (102 endpoints, 16 entities, 19+41 instances, 1468 calls scanned.)

**Notable design decisions:**
- **Posture gating uses final (approved-only) allowance consumption**, not provisional — I caught during design that a provisional-based posture would make the last cent of allowance un-approvable (submitting a draw that pushes provisional ≥ total would flip posture and block its own approval). Provisional remains an exposed dual-variant field; final drives the `ALLOWANCE_EXHAUSTED` posture and the approve-time cascade that force-holds SUBMITTED draws (depth-2 transitive cascade).
- **Depth-3 cascade** anchored on occupancy-certificate issuance: TIProject PUNCH→CLOSEOUT (hop 1) → Lease abatement/actual-RCD finalization (hop 2) → DRAFT OverageInvoices auto-ISSUED (hop 3).
- **Two interval semantics**: pairwise half-open `[start, end)` overlap for milestones on an engagement (adjacency allowed, tested at 1-millisecond precision) vs. closed-interval aggregate capacity counting for concurrent construction windows per Property (shared boundary day = conflict).
- **Segregation of duties** between LandlordPM and LandlordApprover keyed on `X-User-ID`: a CO approver cannot approve any draw on the same project (`ERR_SEGREGATION_OF_DUTIES`).
- **3 true OCC races** (work-letter counter, CO create, draw create) all on parent `version` with `expected_*_version` placeholders captured from prior reads — no literals.
- All money math pre-computed to literals (retainage tier boundary at exactly 50% → 5% tier; per-line markup `[1005,1005]` → 2212 vs 2211; abatement 1,000,000 calendar vs 800,000 business; overage share 2,100,000 across headroom) and verified with Python before pinning into asserts.

## Step 3: Copy Shared Files — 2026-08-14T04:25:43.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1628_tenant_improvement_project_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T04:41:35.000Z

The "around" on line 191 is narrative ("sending it back around the loop"), not a numeric hedge — acceptable. All audits are complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1628_tenant_improvement_project_management/workspace/PRD.md` — **352 lines**.

**Sections covered:**
- §1 Introduction (2 paragraphs — business context + segregation-of-duties angle)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity translation (`TenantRep`/`ContractorRep` entity-backed; the four opaque roles named individually), 2.2 response envelope (**byte-verbatim** from `section-2.2-response-structure.md`, verified programmatically), 2.3 pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), 2.4 resource identity + sequential numbering, 2.5 logical clock (startup default 2026-08-01T00:00:00Z), 2.6 integer-cents/round-half-up, 2.7 the 8-stage validation funnel with six per-endpoint pinned check orders, 2.8 OCC (all 3 rules), 2.9 cascade philosophy, 2.10 left-to-right path validation
- §3 Business Logic (8 subsections, chronological-lifecycle grouping): portfolio setup → work-letter negotiation → plan review → contractor/engagement/scheduling → change orders → disbursements/retainage/lien waivers → punch/occupancy/rent abatement → invoicing/closeout/cancellation
- §4 Endpoint table (72 endpoints, 4 columns only); §5 Error catalogue (31 errors, 2 columns only)

**Zero-Silence / Hard-Contract self-audit — all PASS:**
- **Contract 1 (Field coverage):** 98 required identifiers (all `entities[].fields`, all endpoint inputs incl. `to_iso8601`, `issued_on`, both OCC fields, pagination fields) — 98 present in backticks, 0 missing (two passes; first pass caught extraction misalignment from fenced JSON, fixed by stripping fences before tokenizing).
- **Contract 2 (Rule coverage):** validation priorities (32 rules → 8-stage funnel + 6 explicit per-endpoint orderings incl. draw-approval's 6-check ladder), 3/3 OCC rules with write-endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412, all 14 state machines' transitions with preconditions and side effects, all 9 calculations as reconstruction-safe prose (per-line-then-sum markup pinning, retainage 10%/5% tier with equal-to-threshold → late boundary, overage sweep with `approved_at`/`created_at` ordering, closed vs half-open interval semantics, posture ≥ boundary, 365-day half-up daily rent, 30-day due date with dual effective-date paths), all `applies_to` scopes enumerated, all defaults/initials stated (incl. `round_number` 0, submission `version` 1 — added in repair pass), sibling branches symmetric (cancel cascade rendered per-phase for all 7 non-terminal states). 31/31 error IDs appear in §2/§3 narrative.
- **Contract 3 (§3 path purity):** 585 backticked tokens scanned — 0 paths, 0 bare methods, 0 method+path tokens. Endpoints referenced via state pairs (`PROPOSED` → `COUNTERED`), role+verb, or capability descriptions.
- Pseudocode scan: no `==`/`>=`/`<=`/`!=`/`+=`/boolean operators in prose; no fuzzy hedges ("approximately"/"roughly"/etc. — the one "around" hit is idiomatic, not numeric).

**Notable scattering/encoding decisions:**
- Endpoint inputs deliberately split across subsections: e.g., draw creation fields (`period_end_date`, `requested_amount_cents`, `is_final_draw`, OCC field) in §3.6 intro while `approved_amount_cents` and its two fiscal ceilings appear later in the approval paragraph; CO `lines` structure in §3.5 creation vs. markup/overage math in the approval paragraph.
- Constants embedded narratively without unit games that would lose precision: "ten percent"/"five percent"/"half of the allowance"/"divided by 365"/"thirty days" — all reconstructible.
- The scaffold's CO-submit tension (transition says `posture != ALLOWANCE_EXHAUSTED`, validation 27 says `OPEN`) was resolved to the stricter joint reading — "posture must be `OPEN`" with `ERR_PROJECT_NOT_OPEN` — which uniquely determines both entries.
- Preconditions the scaffold leaves without a nominated error (e.g., revoke-blocked-while-ACTIVE, milestone-terminal gates) are stated factually and mapped to the §2.7 stage-6 lifecycle guard (`ERR_INVALID_STATE`) rather than inventing new error IDs.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; no sibling task directories were inspected.

## Step 5: Generate Unit Tests — 2026-08-14T05:19:44.000Z

Generation complete. All artifacts are under `/home/ubuntu/github/CodingPRD/tasks/task_1628_tenant_improvement_project_management/`.

## Files written

**test_helpers/ (9 files):**
- `types.py` — role enum + 13 status enums + 15 entity TypedDicts (all entities carry id/created_at/updated_at/version per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~75 methods)
- `api_errors.py` — `ApiErrorId` (32 ids) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators, ledger/retainage/overage invariant checkers, `parse_instant`
- `factories.py` — input-field-only payload factories per entity
- `constants.py` — retainage tiers (10%/5%, 50% threshold), 10% markup, 365 divisor, 30-day invoice offset, capacity default 2
- `test_users.py` — `TEST_USERS` for opaque roles + mandatory `make_tenant_rep_headers`/`make_contractor_rep_headers`/`make_landlord_approver_headers` builders for entity-backed/SoD-sensitive identities
- `fixtures.py` — composite lifecycle fixtures: `setup_project_negotiated` / `_in_plan_review` / `_in_pre_construction` / `_in_construction` / `_in_punch`, multi-project drivers (`drive_lease_to_pre_construction`, `drive_project_to_construction`), OCC-aware draw/CO helpers that re-read the project version before every create, verified-waiver draw ladder, punch handshake flows
- `__init__.py` — barrel export

**test_suite/ (11 files):** `conftest.py` + `test_01_portfolio_envelope.py`, `test_02_work_letter_negotiation.py`, `test_03_plan_review.py`, `test_04_contractor_engagement.py`, `test_05_schedule_and_capacity.py`, `test_06_change_orders_invoicing.py`, `test_07_disbursement_ledger.py`, `test_08_draw_gates_posture.py`, `test_09_punch_certification_abatement.py`, `test_10_project_lifecycle.py`.

## Test counts
- **Total: 80 tests** (all collected by pytest; all compile; pyflakes clean)
- **Queue A (§1.8 difficulty): 39 tests** — all 19 instances covered, 17 with exactly 2 tests and `draw_approval_exactly_remaining_allowance` with 3 (exact-boundary success, one-cent-over rejection, below-boundary posture stays OPEN)
- **Queue B (§1.9 corner): 41 tests** — all 41 non-stub instances covered with ≥1 test each

## Instances skipped
No testable instance was skipped. The only non-translated entries are the **7 `excluded_because:` stubs** (never translated by design): `calculations/retainage_tier_boundary_covered_by_difficulty` and the six `errors/*_residual` stubs. All 7 `difficulty_instance` cross-references were verified to resolve to real §1.8 instances.

Two sub-assertions inside otherwise-covered instances failed the two-reader test and were dropped (not weakened to status checks): (1) `Property.version == 1` in `property_creation_applies_default_capacity` — PRD pins initial version 1 only for plan submissions (§3.3), so the absolute initial value on Property is not uniquely derivable; the default-capacity claim (PRD §3.1) is asserted instead; (2) `approved_amount_cents == 0 / net_payment_cents == 0` at draw creation in `disbursement_computed_fields_ignore_client_input` — PRD never names the pre-approval value (null is equally faithful); the PRD-pinned `draw_number` sequencing (1, 2) and DRAFT initial state are asserted. Relatedly, the punch-item reopen test asserts `version == created + 6` (PRD §2.4 delta) rather than the absolute 7.

## Stage 2 self-audit result
- **Tag coverage: PASSED.** 80/80 tests carry exactly one `Design:` line; every tag resolves to a real instance in the cited yaml; no tag points at a stub; every difficulty instance has ≥2 tagged tests; every non-stub corner instance has ≥1.
- **PRD citations: PASSED.** 134 quoted citations across 80 docstrings, every one verified verbatim against PRD.md (whitespace-normalized literal grep), each naming the rule-bearing sentence (error id, threshold, transition, or side effect).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; no freelance tests beyond the two design indices.

## Step 6: Generate Implementation — 2026-08-14T05:19:44.000Z

102 endpoints in the scaffold, 102 route handlers in the implementation. Full coverage.

Here is the summary.

---

## Implementation Summary

### Files Written (16 source files + start.sh + requirements.txt)

| File | Purpose |
|---|---|
| `start.sh` | Launcher: guarded `pip install`, `exec python3 app.py`, reads `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask app entry point, blueprint registration, error handlers (APIError, 404, 405, 500) |
| `db.py` | In-memory `Store` singleton: 16 entity dicts + logical clock (default `2026-08-01T00:00:00.000Z`). No seeding, no persistence. |
| `errors.py` | `APIError` exception class + all 28 error ID constants + shortcut constructors |
| `response.py` | Envelope helpers: `success_object`, `success_created` (201), `success_list` (with pagination meta), `error_response` |
| `middleware.py` | Auth: `get_auth()` (X-User-ID / X-User-Role presence), `require_roles()` (RBAC), scope checks (`check_tenant_ownership`, `check_contractor_ownership`) |
| `services/util.py` | ID minting (UUID4), ISO8601 parse/format (3-fractional-digit Z), pagination params (limit/offset defaults 10/0, min 1, max 100), `round_half_up_cents` via Decimal, `bump_version` |
| `services/calc.py` | All 8 calculation rules |
| `services/cascade.py` | Project cancellation compensation cascade + lease auto-termination |
| `routes/clock.py` | 1 endpoint |
| `routes/portfolio.py` | 13 endpoints (Property, LeaseSpace, Tenant, Lease CRUD + activate) |
| `routes/contractors.py` | 8 endpoints (Contractor CRUD + qualify/suspend/reinstate/revoke) |
| `routes/projects.py` | 9 endpoints (TIProject create + 7 lifecycle transitions) |
| `routes/work_letters.py` | 8 endpoints (WorkLetter CRUD + propose/counter/accept/execute/withdraw) |
| `routes/plans.py` | 11 endpoints (PlanSubmission + PlanReviewComment CRUD + review actions) |
| `routes/engagements.py` | 10 endpoints (ContractorEngagement CRUD + 7 lifecycle actions) |
| `routes/milestones.py` | 6 endpoints (ScheduleMilestone CRUD + confirm/complete/cancel) |
| `routes/change_orders.py` | 7 endpoints (ChangeOrder CRUD + submit/approve/reject/void) |
| `routes/disbursements.py` | 13 endpoints (DisbursementRequest + LienWaiver CRUD + lifecycle) |
| `routes/punch_items.py` | 8 endpoints (PunchItem CRUD + start/resolve/verify/reopen) |
| `routes/invoices.py` | 8 endpoints (OverageInvoice CRUD + issue/pay/dispute/reissue/void) |

### Endpoint Count: 102 / 102 (full scaffold coverage)

### Organization of Key Concerns

**State machines** (13 entities): Implemented as inline transition logic in each route handler. Each endpoint validates the current state before transitioning. The validation funnel (PRD section 2.7) is enforced: auth -> role -> scope -> existence -> body -> state -> business rules -> OCC. Business check ordering within stage 7 is pinned per endpoint (e.g., engagement approval: building rules -> insurance -> qualification; occupancy cert: LIFE_SAFETY first -> all items; draw approval: waiver exists -> amount match -> SoD -> posture -> exceeds request -> exceeds remaining).

**Calculations** (8 rules): All in `services/calc.py`. Uses `Decimal` with `ROUND_HALF_UP` for all monetary multiplications. Key calcs: `change_order_markup` (per-line round-then-sum, pinned), `change_order_overage_share` (chronological headroom sweep), `disbursement_retainage` (tiered by cumulative consumption vs 50% threshold, final draw = 0), `rent_abatement` (CALENDAR vs BUSINESS day counts, daily rate = round_half_up(annual/365)), `property_construction_capacity` (closed-interval intersection), `milestone_window_overlap` (half-open semantics), `project_posture` (threshold + cascade), `invoice_due_date` (+30 days).

**Validation funnel**: Implemented via the middleware + route handler pattern. `require_roles()` handles stages 1-2. Scope checks handle stage 3. Entity lookups handle stage 4 (left-to-right path validation). Body validation is stage 5. State checks are stage 6 (returning 409 ERR_INVALID_STATE). Business rules are stage 7 (in pinned per-endpoint order). OCC is stage 8 (last, returning 412 ERR_STALE_VERSION).

**OCC**: Three endpoints check expected version: `POST /api/work-letters/{id}/counter` (checks `expected_work_letter_version` against WorkLetter.version), `POST /api/ti-projects/{id}/change-orders` and `POST /api/ti-projects/{id}/disbursement-requests` (both check `expected_ti_project_version` against TIProject.version). The check runs after all business rules pass.

**Cascades**: `services/cascade.py` handles project cancellation (the compensation cascade widens by project phase, per PRD section 3.8) and lease auto-termination when all projects are terminal. `services/calc.py` `recompute_posture()` handles the SUBMITTED/ON_HOLD draw flip cascades. Contractor suspend cascades to ACTIVE engagements. Occupancy certificate issuance auto-issues DRAFT invoices.

### start.sh Boot Verification

Confirmed working: `bash start.sh` from the `implementation/` directory boots on `$PORT`, binds `0.0.0.0`, and responds within 2 seconds. Smoke-tested:
- 404 on unknown route (server is up)
- `POST /_clock/set_current_utc` returns 200 with correct envelope
- `POST /api/properties` returns 201 with correct envelope
- Missing auth headers return 401 ERR_UNAUTHENTICATED
- Wrong role returns 403 ERR_UNAUTHORIZED_ROLE
- Full end-to-end flow: property -> space -> tenant -> lease -> activate -> project -> work letter negotiation -> plan review -> engagement -> construction -> change order approval (markup = 30000 on 300000) -> draw approval (retainage = 200000 on 2000000 at early 10% tier) -> all monetary fields correctly computed

## Step 7: Run Tests and Iterate — 2026-08-14T05:43:05.000Z

# Summary

**Exit condition met: all 8 parallel rounds clean (80/80 passed, 0 failed, 0 errors per round).**

## Iterations run
2 effective iterations (iteration 1: 77/80 × 8 rounds, identical 3 failures in every round; final sweep: 8/8 clean). One intermediate sweep's wrapper was killed by host-level contention from other pipelines after all pytest logs already showed 80/80, so it was re-run to obtain formal results files.

## Tests deleted
None.

## Fixes applied to `test_suite/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1628_tenant_improvement_project_management/test_suite/test_10_project_lifecycle.py` — `TestProjectComputedRead::test_project_read_exposes_computed_monetary_fields`: assertion `total_cost_cents == 40_000_000` contradicted PRD. §3.2 lists `total_cost_cents` among the accumulators that "start at 0", and §3.5 recomputes it to `base_contract_cents + sum(APPROVED CO totals)` only on change-order approval; the test asserted at a point where no approval had run, so the uniquely-determined value is 0. Corrected the assertion to `== 0` with the PRD derivation in the message (STEP 2 — assertion mis-translated PRD wording).

## Fixes applied to `test_helpers/`
None — fixture/factory layer was PRD-faithful throughout.

## Fixes applied to `implementation/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1628_tenant_improvement_project_management/workspace/implementation/routes/disbursements.py` — `pay_disbursement`: the final-draw escrow release zeroed the project's `retainage_held_cents` and then `calc.recompute_retainage` immediately re-derived it from the per-draw withholding fields, stomping the zero (observed: held stayed 3,000,000 after final pay). Now the release also zeroes each contributing APPROVED/PAID draw's `retainage_held_cents`, keeping the derived balance consistent with PRD §3.6 ("the held balance is zeroed").
- `/home/ubuntu/github/CodingPRD/tasks/task_1628_tenant_improvement_project_management/workspace/implementation/services/calc.py` — `recompute_posture`: when leaving `ALLOWANCE_EXHAUSTED`, the new posture was derived from the still-`ON_HOLD` child draws before the release cascade ran, so it settled on `ON_HOLD` and the cascade never fired (PRD §3.6: "leaving it back to `OPEN` returns every `ON_HOLD` draw to `SUBMITTED`"). Now an exhausted project whose consumption drops below the pool goes straight to `OPEN` and the `ON_HOLD` → `SUBMITTED` release cascade runs.

## Step 8: Finalize PRD — 2026-08-14T05:50:00.000Z

Done. PRD_FINALIZED.md is written with exactly two in-place insertions, both tracing to the step_7_diff implementation fixes.

## Summary

**Line counts / delta:** PRD.md 352 lines vs PRD_FINALIZED.md 352 lines — 0% delta (both edits extend existing lines in place; no lines or sections added).

**Changes (one bullet each):**
- §3.6 (posture paragraph) — insert — appended: "That exit is direct: a posture recomputation that finds consumption back below the pool settles the posture at `OPEN` — never `ON_HOLD` — and releases the held draws in the same recomputation, since a draw reaches `ON_HOLD` only as a product of the exhaustion cascade." — `implementation/services/calc.py:105-147` (the fixed `recompute_posture` branch order).
- §3.6 (payment paragraph) — insert — appended: "The release runs through to the draws that fed the escrow: in the same payment, every draw of the project still `APPROVED` or `PAID` has its own `retainage_held_cents` zeroed, so the project's held balance remains the sum of the surviving per-draw withholdings; only the paid draw and the project advance their `version` in this operation." — `implementation/routes/disbursements.py:249-271` (the fixed `pay_disbursement` final-draw release loop).

**Step 7 items needing no edit:** the `test_10_project_lifecycle.py` fix was a pure test mis-translation — PRD §3.2 already pins `total_cost_cents` among the accumulators that "start at 0" and §3.5 pins its recompute to change-order approval; `implementation/routes/projects.py:60-81` initializes all accumulators to 0 exactly as written. PRD prose kept verbatim.

**Per-edit pre-edit search log:**

*Edit 1 (posture exit):*
- (a) Subject: posture derivation/cascade when consumption falls back below the pool while posture is `ALLOWANCE_EXHAUSTED`.
- (b) Paths enumerated and read/grepped: `services/calc.py:105-147` (`recompute_posture` — full branch order; `ON_HOLD` assigned only at line 139, the entry cascade); all seven call sites — `routes/disbursements.py:157-158` (submit), 228-230 (approve), 268-270 (pay), 287-288 (reject), 313-315 (approver-void), `routes/change_orders.py:172-173` (approve), 219-220 (void), `services/cascade.py:87-89` (cancel); all posture consumers — `disbursements.py:149,206`, `change_orders.py:133` (all `posture != "OPEN"` gates); `projects.py:66` (initial `OPEN`); `work_letters.py:181-210` (execute sets pool, leaves posture alone — safe since consumption is 0 there).
- (c) Wording adjustment: deliberately did not delete or rewrite the middle derivation clause ("otherwise `ON_HOLD` when any draw sits in `ON_HOLD`") — the impl still contains that branch (unreachable in practice); instead the added sentence scopes itself to the exit case and asserts `ON_HOLD`-entry only via the exhaustion cascade, which every enumerated path satisfies.

*Edit 2 (final-draw per-draw zeroing):*
- (a) Subject: per-draw `retainage_held_cents` fields on final-draw payment.
- (b) Paths enumerated and read/grepped: `projects.py:78-79` (init 0); `disbursements.py:81` (draw init 0); `calc.py:158-176` (`compute_retainage` at approval, final draw → 0); `calc.py:87-99` (`recompute_retainage` — project held derived as sum over `APPROVED`/`PAID` draws); `disbursements.py:221-231` (approve: compute + derive); `disbursements.py:236-273` (pay — the fix site: zeroes project balance plus every `APPROVED`/`PAID` draw's per-draw held, bumps only the paid draw and project); `disbursements.py:293-318` (approver-void: draw leaves the `APPROVED`/`PAID` set, its field survives but drops out of the derived sum); `cascade.py:76-89` (cancel: voids non-`PAID` draws then re-derives; `PAID` draws' fields survive); `services/util.py:110-112` (`bump_version` = version+1 and `updated_at` refresh).
- (c) Wording adjustments: (i) scoped the zeroing strictly to the final-draw payment so the void and cancellation paths — which do not zero per-draw fields — are not mis-described; (ii) included the "only the paid draw and the project advance their `version`" clause because §2.4's universal version rule would otherwise push a fresh implementer to bump the zeroed sibling draws, which the impl never does (verified no posture flip is reachable at pay time, since payment does not change consumption); (iii) phrased the held-balance invariant as "sum of the surviving per-draw withholdings," which holds on every enumerated path.

## Step 9: Complete PRD — 2026-08-14T06:15:43.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1628_tenant_improvement_project_management/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then edited in place).

**Size:** source `PRD_FINALIZED.md`: 352 lines / 60,327 chars (wc) → `PRD_COMPLETED.md`: 352 lines / 65,443 chars; delta **+5,116 chars**, 0 net line change (all edits are in-paragraph inserts/revisions; no new sections).

**Counts:** 17 ambiguity-pins, 11 mismatch-revisions (the §2.7 funnel reorder counted once; the two wall-clock revisions and their §2.5 support sentence counted separately).

Changes, each `{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`:

- §2.1 — insert — ambiguity — Tenant self-scope compares against tenant's own `id`; ContractorRep gets filtered (not rejected) results on a project's engagement list and a draw's waiver list — `implementation/middleware.py:40`, `implementation/routes/portfolio.py:146`, `implementation/routes/engagements.py:68-69`, `implementation/routes/disbursements.py:374-381`.
- §2.3 — insert — ambiguity — non-integer/out-of-bounds `limit`/`offset` → `ERR_INVALID_REQUEST` (400); `offset` must be ≥ 0 — `implementation/services/util.py:69-86`.
- §2.5 — insert — mismatch (supporting) — `created_at`/`updated_at`/`submitted_at`/`approved_at` are server wall-clock stamps, not logical-clock readings — `implementation/db.py:10-13,47-50`.
- §2.7 — revise — mismatch — funnel stage order changed from auth→role→scope→existence→body→lifecycle to impl's auth→role→existence→scope→lifecycle→body→business→OCC — e.g. `implementation/routes/projects.py:42-53`, `implementation/routes/work_letters.py:117-144`.
- §2.7 stage 3 — insert — ambiguity — body-referenced ids (lease `space_id`/`tenant_id`, engagement/waiver `contractor_id`, punch `assigned_engagement_id`) validated after body well-formedness, as 404 — `implementation/routes/portfolio.py:196-199`, `implementation/routes/engagements.py:42-44`, `implementation/routes/disbursements.py:343-345`, `implementation/routes/punch_items.py:48-50`.
- §2.7 stage 4 — insert — ambiguity — scope-check placement pinned: after existence/before lifecycle+body, except counter/accept (after project-phase gate), change-order creation (after body), waiver creation (after body + contractor existence); ContractorRep access to projects/change-orders/draws/project-punch-list unscoped; CO submit, draw submit, contractor DRAFT-draw void unscoped — `implementation/routes/work_letters.py:121-127`, `implementation/routes/change_orders.py:64-66,122-137`, `implementation/routes/disbursements.py:347-351,48,122,298-303`.
- §2.7 stage 5 — insert — ambiguity — blanket: all unnamed related-entity state guards (suite VACANT at activation, milestones-terminal at punch entry, no-CONFIRMED at termination, phase gates on engagement activate/complete/CO-submit/draw-submit/invoice-issue/punch-log/verify/reopen, comment create/resolve, waiver verify/reject, ACTIVE gates, completion ledger) surface `ERR_INVALID_STATE` (409) — e.g. `implementation/routes/portfolio.py:240-241`, `implementation/routes/projects.py:216,299-308`, `implementation/routes/engagements.py:174,198-209`.
- §2.7 bullets — insert — ambiguity — milestone creation: STANDARD auto-confirm's engagement-ACTIVE check runs after overlap and window-shape checks; confirmation re-runs overlap (excluding self) only after the ACTIVE check — `implementation/routes/milestones.py:55-67,113-127`.
- §2.7 bullets — revise — mismatch — draw-approval ladder step 2: "some verified waiver's amount matches" (any-match, not the-one-waiver) — `implementation/routes/disbursements.py:193`.
- §3.1 — revise — mismatch — `suite_number` uniqueness not enforced; `floor` pinned as integer — `implementation/routes/portfolio.py:60-77`.
- §3.1 — revise — mismatch — `scheduled_rent_commencement_date` stored as parsed ISO 8601 rendered in UTC (date-only → midnight), not midnight-normalized — `implementation/routes/portfolio.py:185-206`.
- §3.2 — insert — ambiguity — further work-letter drafts may be created in `INITIATED` or `WORK_LETTER_NEGOTIATION`; only the first advances the phase — `implementation/routes/work_letters.py:40-41,66-68`.
- §3.2 — revise — mismatch — phase requirement applies to propose/counter/accept only; execute and withdraw consult only the letter's own state — `implementation/routes/work_letters.py:103,121,166` vs `181-198,213-221`.
- §3.3 — revise — mismatch — `submitted_at` is the server's wall-clock timestamp, not a logical-clock reading — `implementation/routes/plans.py:63`.
- §3.4 — revise — mismatch — `insurance_expiry_date` stored as parsed ISO 8601 in UTC, not forced to midnight — `implementation/routes/contractors.py:29-38`.
- §3.4 — insert — ambiguity — engagement proposal not gated on project phase; rules acknowledgement not state-gated and repeatable (re-bumps) — `implementation/routes/engagements.py:29-55,83-90`.
- §3.5 — insert — ambiguity — CO creation not phase-gated; draft opens with computed fields 0 and `submitted_by`/`approved_by_user_id`/`approved_at` null — `implementation/routes/change_orders.py:49-91`.
- §3.5 — revise — mismatch — submission is by any ContractorRep/TenantRep (no ownership check), not "its originator" — `implementation/routes/change_orders.py:122-137`.
- §3.5 — revise — mismatch — `approved_at` is wall-clock, not the logical-clock reading — `implementation/routes/change_orders.py:167`.
- §3.5 — revise — mismatch — CO-void block applies once the order is in an invoice manually issued or paid and not since voided; certificate-auto-issued invoices don't block until paid; the bookkeeping flag lives on (and appears in) the CO record — `implementation/routes/change_orders.py:207`, `implementation/routes/invoices.py:121-124,140-143,180-183`, `implementation/routes/projects.py:279-285`.
- §3.6 — insert — ambiguity — draw creation ungated by phase/scope, bumps project `version`, draft defaults 0/null — `implementation/routes/disbursements.py:47-90`.
- §3.6 — insert — ambiguity — submit/reject refresh derived allowance fields without bumping project `version`; creation/approval/payment/approver-void do bump it — `implementation/routes/disbursements.py:153-158,281-288`.
- §3.6 — insert — ambiguity — waiver attachment not gated on draw state — `implementation/routes/disbursements.py:325-362`.
- §3.6 — insert/revise — ambiguity+mismatch — `approved_amount_cents` pinned as integer ≥ 0; ladder step 2 requires at least one matching verified waiver — `implementation/routes/disbursements.py:176,193`.
- §3.7 — insert — ambiguity — punch item's `assigned_engagement_id` validated only for existence (need not belong to project nor be ACTIVE at logging) — `implementation/routes/punch_items.py:47-50`.
- §3.8 — revise — mismatch — invoice drafting sweeps APPROVED orders with positive share not yet in any **non-VOID** invoice (voided invoices free their orders) — `implementation/routes/invoices.py:35-50`.
- §3.8 — insert — ambiguity — drafting not gated on project phase; reissue leaves `due_date` unchanged; voiding releases included orders (re-invoiceable, unblocks §3.5 void) — `implementation/routes/invoices.py:53-63,161-169,172-187`.
- §3.8 — revise — mismatch — manual issue sets `due_date` to the current logical-clock **reading** + 30 days (timestamp-exact, not date-truncated) — `implementation/routes/invoices.py:118`, `implementation/services/calc.py:286-290`.

Everything else in the PRD (endpoint table, role lists, all six pinned business-check ladders, markup/overage-sweep/retainage/abatement formulas, posture machine and cascades, cancellation matrix, OCC contract, envelope shape) was verified line-by-line against the implementation and already matched uniquely, so it was left untouched.
