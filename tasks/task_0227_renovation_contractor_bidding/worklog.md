# Worklog — task_0227_renovation_contractor_bidding

## Step 1: Create task directory — 2026-06-07T00:00:00.000Z

Created `tasks/task_0227_renovation_contractor_bidding/` with `workspace/` subdirectory. Using the explicitly-provided task_dir (skipped Step 1 index scan to avoid ID contention with parallel tasks). Difficulty: Expert.

## Step 2: Generate scaffold — 2026-06-07T00:10:00.000Z

Generated the three scaffold artifacts for **task_0227_renovation_contractor_bidding** (Expert difficulty). All three parse as valid YAML and `scaffold_lint.py` returns **VERDICT: clean lint** (632 calls scanned across §1.8+§1.9; all FK reverse-reachability satisfied).

**Complexity profile:** primary archetype `multi_party_negotiation` (homeowner ↔ contractors bid/award) + secondary `ledger_reconciliation` (escrow funded/released/retained); layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; hybrid topology; branching state-machine shape; peer_roles; immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities** — Contractor, Project, Homeowner, ScopeLineItem, Bid, BidLineItem, Milestone, Escrow, Draw, LienWaiver, ChangeOrder, Dispute
- **7 state machines** — Contractor (PENDING↔SUSPENDED→REVOKED), Project (DRAFT→…→COMPLETED with DISPUTED revert), Bid (cyclic SUBMITTED↔REVISING), Milestone, Draw (branching DISPUTED→{APPROVED,REJECTED}), ChangeOrder, Dispute; **2 concurrency rules** (OCC on Project.version for award, on Bid.version for change-order approve)
- **6 calculations** — bid_line_total, project_estimate, bid_rank_score (estimated/award variants), draw_release_amounts (provisional/final variants), escrow_available, contractor_average_rating
- **17 validations** (priority-ordered, auth → existence → state → OCC → temporal → safety → referential → constraint → fiscal)
- **54 endpoints** (high read count driven by mandatory FK reverse-reachability GETs + 1 `/_clock` test-driving endpoint; api_prefix set to `""` so flat top-level collections register their segments)
- **18 error codes**
- **5 roles** — Homeowner (entity_backed), Contractor (entity_backed), EscrowAgent (opaque), PlatformAdmin (opaque), Anonymous

**SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 = **18 instances**, all grounds resolve, all formula-derived asserts pre-computed as literals (verified with round_half_up: draw 12345/1235/11110, rank scores 0.20/0.35/0.70/0.75/1.00, avg 4.50, estimate 16983, bid total 4014).

**SCAFFOLD_CORNER_DESIGN.yaml:** **39 instances** across 9 taxonomy sections (35 full recipes + 4 `excluded_because` stubs, all citing real §1.8 instances). All 57 instance names unique across the union; no forbidden concurrency vocabulary anywhere.

Design note: the milestone-sequence-collision rule (`ERR_MILESTONE_SEQUENCE_TAKEN`, priority 13) was added to give the `resource_temporal_overlap` difficulty rule a second, geometrically-distinct interval semantics (discrete-ordinal point-uniqueness) alongside the draw sequential-adjacency gating rule.

## Step 3: Copy INSTRUCTION.md — 2026-06-07T00:11:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0227_renovation_contractor_bidding/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-07T00:20:00.000Z

Generated `workspace/PRD.md` — a prose PRD for the Renovation Contractor Bidding API (~6,050 words, 270 lines, ~41 KB). Read SCAFFOLD.yaml only; both design YAMLs withheld.

### Section structure
- §1 Introduction — multi-party negotiation + escrow-ledger duality.
- §2 Global Specifications (10 subsections): 2.1 RBAC (all 5 roles), 2.2 Response Structure (canonical block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Monetary/Rounding (per-line-then-sum), 2.6 Escrow Ledger Integrity, 2.7 Sequential Milestone Schedule, 2.8 Nested Retrieval/Existence, 2.9 OCC, 2.10 Logical Clock.
- §3 Business Logic (9 subsections, lifecycle-organized): contractor qualification, project drafting, opening/bidding window, comparison/award cascade, escrow funding, draw pipeline (request/approve/pay), change orders, completion/rating, disputes.
- §4 4-column endpoint table (all 54 endpoints), §5 2-column error table (all 18 errors).

### Coverage
- Entities: all 11 with every field named. Endpoints: 54/54 in §4. State machines: all 7 lifecycles with from/to, preconditions→error IDs, cascades. Calculations: all 6 (bid_line_total, project_estimate, bid_rank_score 0.5/0.3/0.2 weights 4dp, draw_release_amounts 10% retainage round-then-subtract, escrow_available invariant, contractor_average_rating 2dp). OCC: both rules (ERR_STALE_PROJECT_VERSION, ERR_STALE_BID_VERSION, 412). Validations: all 17 matchable to error IDs; submit-time precedence explicit.

### Hard Contract reports: Field coverage PASS (64/64), Rule coverage PASS (validations, 2 OCC, 7 SMs, 6 calcs, sibling symmetry), Path purity PASS (§3 only, 0 path tokens). No withheld design file opened.

## Step 5: Generate unit tests — 2026-06-07T00:40:00.000Z

Generated complete test infrastructure from the two design indices (the only test source), with strict PRD-first adjudication.

### Test helpers (Stage 1) — 9 modules
`test_helpers/`: `types.py` (12 entity TypedDicts; 12 status enums + role enum), `api_client.py` (~54 endpoint methods), `api_errors.py` (18 error IDs + HTTP-status map), `assertions.py` (per-entity + `assert_escrow_invariants`), `factories.py` (input-field-only payload factories; `min_rating` optional per PRD), `constants.py` (MIN_INSURANCE_CENTS, RETAINAGE_PCT, rank weights, clock defaults), `test_users.py` (opaque shared constants + `make_homeowner_headers`/`make_contractor_headers` identity-threading builders), `fixtures.py` (tiered composite setup → DRAFT project → submitted bids → award+fund → draw pipeline → change orders + `round_half_up` helper), `__init__.py`.

### Test suite (Stage 2) — 6 files, 71 test functions
`test_01_calculations.py` (13), `test_02_bid_lifecycle.py` (11), `test_03_award_and_escrow.py` (8), `test_04_draw_pipeline.py` (21), `test_05_crud_rbac_and_lifecycle.py` (18), + `conftest.py`.

### Coverage
- Queue A (difficulty): **18/18 instances translated**, 2 tests each (36 tests). 0 skipped — all 9 difficulty rules × 2 instances passed PRD-first filter (submit-time precedence at PRD §3.3 pins state-before-temporal and qualification-before-scope).
- Queue B (corner): **35/35 non-stub instances translated** (35 tests). 0 skipped. The 4 `excluded_because` stubs correctly NOT translated; all 4 `difficulty_instance` cross-refs resolve.
- One unique-derivability adjustment: dropped `version == 1` literal sub-assertion from two creation instances (PRD says "version begins at its initial value" without pinning literal); kept uniquely-derivable field assertions.
- 71/71 tests carry exactly one `Design:` line; all 89 PRD citations survive literal grep; no skip/xfail; all modules byte-compile.

## Step 6: Generate implementation — 2026-06-07T00:40:00.000Z

Generated complete Python + Flask implementation at `workspace/implementation/` (~1,981 lines, 23 files).

### Files
- `start.sh` (executable) — reads `PORT` (default 10000), guards dep install (`if ! python3 -c "import flask"`), `exec python3 app.py`.
- `app.py` (blueprint reg, error handlers, binds `0.0.0.0:$PORT`), `db.py` (in-memory store, empty at boot, logical clock, UUID/ISO helpers — no seeding), `errors.py`, `response.py`, `middleware.py` (auth via `X-User-ID`/`X-User-Role`).
- `services/`: `common.py` (stamping, round-half-up via Decimal, pagination, body parsing), `lookups.py`, `calculations.py` (all 6 calc rules).
- `routes/`: homeowners, contractors, projects, scope_items, bids, escrows, draws, lien_waivers, change_orders, disputes, clock.

### Coverage
All 12 entities, all 54 endpoints. Self-verified via smoke suites: full lifecycle (register→qualify→project/scope/milestones→estimate→open→bid→submit→award OCC→escrow fund→draw request/approve/pay→complete→rate), validation precedence (8 error paths), disputes (OVERTURNED + UPHELD cascades), change orders + OCC on bid version, RBAC/pagination/rank precision/timestamp format. Fresh `bash start.sh` boots empty (`total_count=0`), binds `0.0.0.0:$PORT` foreground, no state carryover. Note: no `GET /homeowners` list endpoint (scaffold only defines POST + GET-by-id).

## Step 7: Test-and-fix loop — 2026-06-07T01:00:00.000Z

**Iterations run:** 2 (initial sweep surfaced 2 failures; second sweep after fixes was clean — all 8 rounds 71/71). Orchestrator re-ran a confirmation 8-round sweep: all 8 rounds passed=71 total=71 failed=0.

**Tests deleted:** None. Both failures traced to genuine implementation defects, not unfair tests.

**Fixes applied to `test_helpers/`:** None. The fixtures and factories were faithful to the PRD.

**Fixes applied to `implementation/`:**

1. **`routes/projects.py` — `award_project()`** — Moved the optimistic-concurrency check (`expected_project_version`) to run *before* the `OPEN_FOR_BIDS` state check. PRD §2.9 verbatim covers and uniquely determines this: "If a prior award (or any other mutation) has already advanced the project's version since the client last read it, the client's view is stale — the project may already have left its open-for-bids state — and the award is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)." Old order returned `ERR_INVALID_STATE` for a second stale award; §2.9 dictates `ERR_STALE_PROJECT_VERSION`. Verified: second stale award now returns 412 ERR_STALE_PROJECT_VERSION.

2. **`app.py`** — Added `socket.getfqdn = lambda *a, **k: "localhost"` before Flask import. Werkzeug's `server_bind()` does a reverse-DNS lookup on the bound host; with the contract-required `0.0.0.0` bind under the runner's DNS isolation, that lookup blocked ~5.0s per boot, pushing boots past the 15s restart window under the concurrent sweep and surfacing as `"API server could not be restarted"` on one test. FQDN is only used for an informational `server_name`, so short-circuiting is behaviour-preserving and keeps the `0.0.0.0` bind. Verified: cold boot 5.17s → 0.108s (~48x).

**Key finding:** the "could not be restarted" failure looked flaky but had a concrete deterministic root cause — a 5-second reverse-DNS stall on the `0.0.0.0` socket bind — only manifesting under the concurrent sweep's CPU pressure. Exactly the boot-latency class of bug the 8-round sweep is designed to catch.

## Step 8: Finalize PRD — 2026-06-07T01:10:00.000Z

Produced `workspace/PRD_FINALIZED.md` (not skipped — Step 7 had 2 implementation fixes). PRD.md = 270 lines, PRD_FINALIZED.md = 270 lines (0.0% delta; single in-place same-line sentence revision).

**Changes:**
- §3.4 (Comparing Bids and Awarding the Work) — revise — Reordered the award precondition sentence so the `expected_project_version` OCC check is described as evaluated *before* the `OPEN_FOR_BIDS` state requirement, and added that a stale-version award returns `ERR_STALE_PROJECT_VERSION` even when the project has already left `OPEN_FOR_BIDS` — `implementation/routes/projects.py:262-267`.

**Items considered but NOT patched:**
- Step 7 item #2 (`app.py` `socket.getfqdn` monkey-patch) — pure boot-time DNS short-circuit; no PRD-observable behavior.

**NO-NEW-MISMATCH pre-edit search:** subject = award OCC-vs-state precedence + error choice. Enumerated `routes/projects.py:award_project()` (OCC precedes state), `routes/change_orders.py:approve_change_order()` (OPPOSITE precedence: state-before-OCC), §2.9 and §2.8. Wording scoped narrowly to the award operation so the OCC-first claim does not bleed onto the change-order-approve path which uses state-first ordering; kept the SUBMITTED/belongs bid check after the OCC clause to match impl (only bid existence runs pre-OCC under §2.8).

## Step 9: Complete PRD — 2026-06-07T01:20:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan (always runs). Source `PRD_FINALIZED.md`: 270 lines / 41,064 chars → `PRD_COMPLETED.md`: 270 lines / 43,028 chars (char delta +1,964; line count unchanged, all in-paragraph inserts/revisions).

**Change counts:** 9 total — 6 ambiguity-pins, 3 mismatch-revisions.

- §2.1 (RBAC) — insert — ambiguity — ownership enforced only on mutating ops; GET/read endpoints perform no ownership check — `routes/projects.py` GETs vs mutations.
- §2.4 (Common Resource Properties) — insert — ambiguity — `version` initial value = 1 at creation — `services/common.py:19`.
- §3.1 (Qualifying Contractors) — insert — ambiguity — all failed qualify/suspend/revoke preconditions return `ERR_INVALID_STATE` — `routes/contractors.py`.
- §3.2 (Homeowner registration) — insert — ambiguity — duplicate-email registration rejected with `ERR_INVALID_REQUEST` — `routes/homeowners.py:22`.
- §3.2 (Project estimate) — insert — ambiguity — sum field name `estimated_total_cents`; estimate read does no ownership check — `routes/projects.py:195,192`.
- §3.3 (Creating a bid) — insert — ambiguity — bids carry `rank_score` present from creation, initialized to 0 before award — `routes/bids.py:40`.
- §3.7 (Change orders) — revise — mismatch — propose imposes no project/bid-state precondition (only existence + ownership); `IN_PROGRESS` enforced solely at approve/reject — `routes/change_orders.py`.
- §3.9 (Disputes) — insert — ambiguity — raising a dispute additionally requires project be `IN_PROGRESS` — `routes/disputes.py:41`.
- §3.9 (Disputes) — revise — mismatch — `subject_id` always resolved as a draw regardless of `subject_type` (incl. CHANGE_ORDER), 404 if no such draw — `routes/disputes.py:30`.

## Pipeline complete — 2026-06-07T01:21:00.000Z

All 9 steps done. Final 8-round stability sweep: all rounds passed=71 total=71 failed=0. Task artifacts complete: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (71 tests), workspace/implementation/ (Flask, in-memory).
