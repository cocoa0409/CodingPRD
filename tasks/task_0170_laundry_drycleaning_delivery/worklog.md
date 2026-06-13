# Worklog — task_0170_laundry_drycleaning_delivery

## Step 1: Create task directory — 2026-06-05T06:05:14.000Z

Created `tasks/task_0170_laundry_drycleaning_delivery/` and `tasks/task_0170_laundry_drycleaning_delivery/workspace/`. INSTRUCTION.md and all six prd-bench skills verified present.

## Step 2: Generate scaffold — 2026-06-05T06:37:58.000Z

Generated all three scaffold artifacts for **task_0170_laundry_drycleaning_delivery** at the **Expert** difficulty band, working purely from the scenario description and the scaffold-generator skill spec (no sibling tasks consulted).

**Files written** (all three, lint-clean):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**Dimensions:**
- **Entities: 11** — SubscriptionPlan, Customer, Subscription, RouteWindow, Locker, Order, Garment, GarmentNote (append-only event log), LockerAssignment, Claim, Invoice
- **Endpoints: 57** — above the nominal 20–32 cap; driven by the scenario's mandated breadth (subscription plans, route windows, lockers + assignment lifecycle, claims adjudication, garment processing); each of 6 lifecycles contributes its own action endpoints. Kept lean otherwise (filtered-list reverse-reachability instead of redundant sub-resource GETs).
- **Error codes: 41** — above the nominal 18–30 cap, again from the entity/lifecycle breadth; every error is triggerable.
- **Calculation variants: 3+** — 8 calculations total; dual-variant calcs on two domains (`garment_line_price`/order totals on Order-cost vs `customer_risk_score` provisional-vs-settled on Customer-risk), plus combinatorial modes (tiered+discount+rush, round-per-line-then-sum, read-before-write subscription billing).
- **State machines: 6** — Order, Garment, Claim, Subscription, LockerAssignment, Invoice; with **4 non-linear**: Order (IN_PROCESSING↔QC_HOLD rework cycle), Garment (CLEANED→CLEANING rewash cycle), Claim (REJECTED→INVESTIGATING appeal cycle) plus Order's branching cancel.

**Difficulty/corner coverage:** §1.8 has all 9 `rule_id`s with 19 instances total (≥2 each). §1.9 has 31 active corner instances + 6 `excluded_because` stubs across all 9 claim-extraction-guide sections. 2 OCC concurrency rules (claim-create vs Order version; change-plan vs Subscription version). `scaffold_lint.py` returns `VERDICT: clean lint` (550 design calls checked; all FKs reverse-reachable).

Note: endpoint (57) and error (41) counts exceed the Expert band's nominal caps. Subagent trimmed aggressively (removed Subscription PAST_DUE/SUSPENDED machine, redundant reverse-reachability GETs, dead enum values/errors); residual count reflects genuine breadth of the mandated scenario (11 coupled entities, 6 lifecycles).

## Step 3: Copy INSTRUCTION.md — 2026-06-05T06:37:58.000Z

Copied `INSTRUCTION.md` (project root) → `tasks/task_0170_laundry_drycleaning_delivery/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T06:45:12.000Z

Generated PRD at `workspace/PRD.md` — **328 lines**. Design files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) withheld; generated from SCAFFOLD.yaml only.

**Major sections:**
- **§1 Introduction** — logistics-plus-plant dual operation framing.
- **§2 Global Specifications** (9 subsections): RBAC (5 roles), Response Structure (verbatim canonical block), Pagination, Common Resource Properties (GarmentNote has only id/created_at), Monetary/Unit/Precision, OCC, Nested Retrieval + existence ordering, Hierarchical Consistency/Cascades, Validation Evaluation Order.
- **§3 Business Logic** (11 subsections, scattering zone): platform config; order intake & garment declaration; scheduling & provisional pricing; pickup/intake/SLA; cleaning/QC/rework loop; QC-pass/invoicing/dispatch/delivery; cancellation unwinding; notes/risk scoring/risk flag; locker assignments/conflicts; claims lifecycle/settlement; reads & test clock.
- **§4 Endpoint Definitions** — 4-column table, all 57 endpoints.
- **§5 Error Code Catalogue** — 2-column table, all 41 errors.

**Coverage (all hard contracts PASS):**
- Contract 1 (Field-Name Coverage): 78/78 required identifiers present verbatim — 0 missing.
- Contract 2 (Rule Coverage): all 12 entities, 6 state machines (incl. 3 cyclic loops), all transitions+preconditions+error IDs+side-effects, all 8 calculations as precise prose with every constant embedded, both OCC rules, 16 priority-ordered validations. All 41 error IDs in prose; all 33 state values + 14 enum values present.
- Contract 3 (§3 Path Purity): 477 §3 backtick tokens, 0 path/method leaks.

Deviation flagged by subagent: §3 has 11 subsections (above 5–9 soft suggestion) — deliberate fit to EXPERT-band domain size (12 entities, 6 state machines, 8 calculations); scattering and rule coverage intact.

## Step 5: Generate unit tests — 2026-06-05T07:02:02.000Z

Generated test infrastructure (test_helpers/) and test cases (test_suite/) for task_0170 entirely from the four input files (SCAFFOLD + both design indices + PRD) plus the unit-test-generator skill spec.

**Test counts:**
- **Total: 69 tests** across 9 test files.
- **Queue A (Difficulty): 38 tests** covering all **19** difficulty instances (each ≥2 tests).
- **Queue B (Corner): 31 tests** covering all **31** non-stub corner instances (≥1 each).

**Skipped instances:** 0 skipped for PRD-filter failure — every non-stub design instance passed the PRD-first two-condition filter. 6 `excluded_because:` stubs correctly NOT translated (their assertions owned by cited difficulty instances; all 6 cross-references resolve).

**test_helpers/ files:** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

**test_suite/ files:** `conftest.py`, `test_01_pricing_and_billing.py`, `test_02_lifecycle_cycles_and_cascades.py`, `test_03_risk_and_invariants.py`, `test_04_gates_conflicts_overlaps.py`, `test_05_resources_crud.py`, `test_06_state_transitions.py`, `test_07_calculations_corners.py`, `test_08_validations_and_errors.py`, `test_09_rbac_occ_consistency.py`

**Verification:** all 69 tests collect under pytest; all 50 distinct `th.*` helper refs resolve; every test carries exactly one `Design:` tag (69/69); all 91 PRD citation chunks verbatim-present; no skip/skipif/xfail; `make_customer_headers(customer_id)` entity-backed builder present (avoids X-User-ID ownership bug); GarmentNote typed with no version/updated_at.

## Step 6: Generate implementation — 2026-06-05T07:02:02.000Z

Generated Python + Flask implementation in `workspace/implementation/` from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md.

**Source files:** `start.sh` (executable foreground launcher), `requirements.txt` (Flask==3.0.3 only), `app.py` (all 50+ routes, error handlers, state machines, calculations, cascades), `db.py` (in-memory dicts + settable logical clock + ISO-8601 timestamps), `constants.py`, `errors.py` (ApiError + error_id→HTTP catalogue), `response.py` (envelope helpers), `helpers.py` (auth, validation, pagination, Decimal round-half-up, garment line pricing), `views.py` (per-entity serializers, documented fields only).

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` foreground, guards pip install behind import check. Boots in ~1s.

**Storage:** in-memory only (db.py module-level dicts). No SQLite/disk/tmp. No seeding — fresh boot returns total_count=0 for every collection.

**PRD ambiguities resolved by impl-gen (Step 8/9 alignment targets):**
1. SLA durations — PRD names STANDARD_SLA_HOURS/RUSH_SLA_HOURS but no magnitudes; chose STANDARD=48, RUSH=24 (honors stated ordering).
2. MAX_APPEALS — named but unvalued; chose MAX_APPEALS=2.
3. Add-garment order state — enforced ERR_INVALID_ORDER_STATE if order not CREATED.
4. change-plan on non-ACTIVE subscription — added ERR_INVALID_SUBSCRIPTION_STATE guard before OCC check.
5. Customer-scoped claim reads — filtered/gated to claims on orders the customer owns (via order.customer_id).

Note: target host Python 3.9.6 — code avoids 3.10+ syntax.

## Step 7: Run tests and iterate — 2026-06-05T12:54:00.000Z

(Resumed run — Step 7 had never actually executed; no results.*.json existed from the earlier killed session.)

Subagent summary (verbatim):

**Iterations run:** 2 (initial sweep found 1 flaky failure; second sweep after fix was clean; a third confirmation sweep was also clean — 24 rounds total, all 69/69).

**Diagnosis:** The first 8-round sweep surfaced exactly the timing-sensitive flakiness the sweep is designed to catch — 7/8 rounds passed 69/69, but round 3 failed `test_occ_stale_order_version_on_claim_create` with `requests.exceptions.ConnectionError: ('Connection aborted.', BadStatusLine('POST /orders/.../pickup HTTP/1.1'))`. This was not an assertion failure; it was a transport-layer connection race. Root cause: the runner's shared `GenericApiClient` (at the uv-cached `prd_bench_local_runner/testing/client.py`) uses a persistent `requests.Session()` with HTTP keep-alive connection pooling. Under the threaded Werkzeug dev server (`app.run(threaded=True)`), a pooled keep-alive socket can be reused by the client at the moment a server worker is tearing the connection down, so the client reads the echoed request line as the status line → `BadStatusLine`. The runner client is shared infrastructure and cannot be modified, so the fix belongs in the implementation.

**Tests deleted:** None. The only failure was a server-side transport race, not a PRD-coverage or unique-derivability problem. The test itself (`test_occ_stale_order_version_on_claim_create`) is PRD-faithful (asserts `ERR_STALE_ORDER_VERSION` at 412 per PRD §2.6).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `app.py` — added an `@app.after_request` hook (`_no_keep_alive`) that sets `Connection: close` on every response. This forces the test client to open a fresh connection per request instead of reusing a pooled keep-alive socket, eliminating the `BadStatusLine`/`ConnectionError` race against the concurrently-closing threaded dev server. This is a transport-hygiene change only — no new endpoint, response field, side effect, or PRD-defined behavior was added or altered.

**Verification:** Two consecutive full 8-round parallel sweeps after the fix (plus the partially-passing initial one) — every round reports `passed=69 total=69 failed=0 errors=0`. Result files cleaned up.

**Orchestrator confirming sweep:** After the subagent exited, the orchestrator ran one more full 8-round parallel sweep (launched with `&`, joined with `wait` in a single foreground bash call) to regenerate the durable `results.{1..8}.json` artifacts and independently confirm green. All 8 rounds: `passed=69 total=69 failed=0 errors=0`. No test files deleted (9 test_*.py files remain).

## Step 8: Finalize PRD — 2026-06-05T12:57:00.000Z

Step 8 was RUN (not skipped): the literal skip condition requires 0 fixes across all of deletions/test_suite/test_helpers/implementation, but Step 7 made 1 implementation/ fix (the `Connection: close` after_request hook), so the conjunction is false. The fix is transport-hygiene only with no PRD-observable behavior, so the subagent correctly produced an empty diff.

Subagent summary (verbatim):

PRD_FINALIZED.md was created as a verbatim copy of PRD.md with no edits — the correct outcome since the only Step 7 change is PRD-invisible.

**Line counts**: PRD.md = 328 lines, PRD_FINALIZED.md = 328 lines. Delta: 0 lines (0.0%). Files are byte-identical (`diff` returns IDENTICAL).

**Changes**: None. PRD_FINALIZED.md is a verbatim copy of PRD.md.

**Rationale**: The sole Step 7 fix was the `_no_keep_alive` `@app.after_request` hook (`app.py:32-35`) that sets the HTTP response header `Connection: close`. This is a pure transport-hygiene change to eliminate a BadStatusLine/ConnectionError race between the pooled keep-alive test client and the threaded Werkzeug dev server. It changes no PRD-observable behavior, so there is no PRD silence to pin and no PRD/impl divergence to reconcile.

**Per-edit pre-edit search log** (no edits made; single subject evaluated and ruled out of scope):
- (a) Subject: the HTTP `Connection: close` response header set by `_no_keep_alive`.
- (b) Impl paths enumerated: `app.py:32-35` (only before/after_request hook); `response.py` (all 3 builders — none reference the header); `grep -rn "headers\["` across implementation/ (assigned only at app.py:34); grep across test_suite/ and test_helpers/ for Connection/keep-alive/after_request (zero references); PRD scan for connection/keep-alive/transport/tcp/socket/response header (only X-User-ID / X-User-Role request headers mentioned).
- (c) Wording adjustment: none — subject is PRD-invisible, out of scope.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` → IDENTICAL (both 55140 bytes).

## Step 9: Complete PRD — 2026-06-05T13:03:00.000Z

Full PRD-vs-implementation scan. Started from PRD_FINALIZED.md (byte-identical to PRD.md). Produced `workspace/PRD_COMPLETED.md`.

Subagent summary (verbatim):

**Source vs. completed:**
- `PRD_FINALIZED.md`: 328 lines, 55,140 chars
- `PRD_COMPLETED.md`: 328 lines, 56,297 chars
- Char delta: **+1,157** (no line-count change; all edits are in-paragraph inserts)

**Counts:** 7 ambiguity-pins, 0 mismatch-revisions. (All gaps were PRD silence; no passage described a behavior contradicting the implementation.)

**Changes (one bullet each):**

- **§3.4 (SLA Clock)** — insert — ambiguity — pinned the SLA magnitudes: standard = 48 hours, rush = 24 hours (PRD only said "longer/shorter, fixed hours") — `constants.py:29-30`, `app.py:605-606`
- **§3.4 (Intake Logging)** — insert — ambiguity — pinned that the garment must be `INTAKE_PENDING` and that this garment-state check runs first, rejecting any other status with `ERR_INVALID_ORDER_STATE` (PRD named only the order `PICKED_UP` gate) — `app.py:624-628`
- **§3.2 (Garment Declaration)** — insert — ambiguity — pinned that adding a garment requires the order to be in `CREATED`, else `ERR_INVALID_ORDER_STATE` (PRD implied "Onto a CREATED order" but gave no error) — `app.py:500-501`
- **§3.1 (Subscription)** — insert — ambiguity — pinned that change-plan requires `status` `ACTIVE`, else `ERR_INVALID_SUBSCRIPTION_STATE`, evaluated before the OCC version check (PRD pinned this only for cancel, not change-plan) — `app.py:301-304`
- **§3.10 (Appeals)** — insert — ambiguity — pinned the maximum allowed appeals = 2 (PRD referenced "the maximum allowed appeals" without a value) — `constants.py:33`, `app.py:1268,1282`
- **§3.11 (Reading Resources)** — insert — ambiguity — pinned that a `Customer`'s claim list is silently scoped to claims on orders they own (others omitted, not an error); `PlatformAdmin`/`ClaimsAdjuster` see all — `app.py:1190-1191`
- **§3.11 (Reading Resources)** — insert — ambiguity — pinned that the order-invoice read returns a list-shaped (`array`) envelope (at most one invoice), paginated/sorted, not a bare single object (PRD's "Get the order's invoice" was singular/ambiguous) — `app.py:980-986`

**Verified already-pinned (no change needed):** all 8 calculations (garment line pricing with 400/300/5kg/900/1.25 magnitudes, estimate/final totals, subscription-credit waterfall, invoice waterfall, customer risk score, order risk flag, claim settlement cap/depreciation/ceiling, locker buffer geometry); all 6+ state machines and their three cyclic loops (order IN_PROCESSING↔QC_HOLD, garment CLEANED↔CLEANING, claim REJECTED→INVESTIGATING); default values (plan `rush_waived`/`active`, order `rush`, locker `hold_buffer_minutes`=30, garment measurement defaults, `rework_requested`); all serializer field shapes including GarmentNote's id/created_at-only shape and Invoice fields; the §2.9 validation precedence chain; OCC exact-equality version semantics; and Customer ownership scoping limited to Order/Subscription/Claim per §2.1.

Per instruction, the `Connection: close` transport header (`app.py:32-35`) was deliberately **not** added to the PRD.

Orchestrator verification: `PRD_COMPLETED.md` present (56,297 bytes, 328 lines); diff vs PRD_FINALIZED.md shows exactly the 7 in-paragraph inserts above; `grep` confirms no `Connection: close` / keep-alive / after_request transport text leaked into the PRD.

## Pipeline complete — 2026-06-05T13:03:00.000Z

All steps done. Final 8-round stability sweep: 8/8 rounds `passed=69 total=69 failed=0 errors=0`. Final artifact `workspace/PRD_COMPLETED.md` exists. Task `task_0170_laundry_drycleaning_delivery` is complete.
