# Worklog — task_1284_structural_steel_fabricator_erector

## Step 1: Create Task Directory — 2026-08-12T19:23:00.000Z

Pre-assigned directory `tasks/task_1284_structural_steel_fabricator_erector/` with `workspace/` subdirectory verified to exist. Step 1 treated as DONE per invocation instructions.

## Resume Check — 2026-08-12T20:00:00.000Z

Directory contents on resume: only `worklog.md` + empty `workspace/`. Steps 2–9 produced nothing; SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, INSTRUCTION.md, PRD.md, test_helpers/, test_suite/, implementation/ all absent. Resuming pipeline from Step 2.

## Step 2: Generate Scaffold — 2026-08-12T20:30:00.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

**Artifacts** (in `/home/ubuntu/github/CodingPRD/tasks/task_1284_structural_steel_fabricator_erector/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts**
- Entities: 12 (Job, ShopDrawing, MillOrder, ErectionSequence, Piece, Welder, Weld, Inspection, ShippingLoad, FieldFix, Backcharge, ProgressBilling)
- State machines: 12 (one per entity; Piece and Weld carry rework/repair cycles, Sequence/Job carry compound bubble-ups)
- Calculations: 8 (piece_percent_complete, net_progress_billing, mill_order_invoice, backcharge_amount, load_weight, welder_continuity, laydown_slot_conflict, welder_window_overlap)
- Endpoints: 60 (incl. `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default); errors: 33; roles: 7 (WELDER is `entity_backed:Welder`, rest opaque)
- Difficulty instances (§1.8): 18 — exactly 2 per rule, all nine rules
- Corner instances (§1.9): 65 total (52 full recipes + 13 `excluded_because` stubs)

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (848 recipe calls scanned, 0 violations; two fix rounds: added 8 GET-by-id endpoints so the FK segment-derivation heuristic could bind, and quoted nested-bracket YAML scalars.)

**Notable design decisions**
- Flat topology (all FKs in bodies, filtered-list GETs for reverse reachability) and `segregation_of_duties` role model: drawing submitter ≠ EOR approver (`ERR_SELF_APPROVAL_FORBIDDEN`), welder ≠ weld inspector (`ERR_SEGREGATION_OF_DUTIES`).
- ShopDrawing revisions are self-referential rows (`supersedes_id`); approving revision N+1 fires the depth-3 cascade: old revision SUPERSEDED → pinned Pieces stale → stale pieces stripped from loads → emptied load LOADING→STAGING. Second cascade: field-fix approve → Backcharge PENDING → Job pending aggregate.
- Two OCC concurrency rules (true create-with-supersede races): drawing `revise` on `expected_drawing_version`, billing create on `expected_job_version`.
- Dual-variant calcs on different domains: progress pct (WEIGHT vs COUNT basis, 0.7000 vs 0.3333 on identical inputs) and mill invoicing (NOMINAL 4500000 vs ACTUAL 4725000 cents). Combinatorial rules in different modes: tiered whole-amount retainage (0.5000 → 4750000 net vs 0.4990 → 4491000) and per-line-then-sum rounding for backcharges (pinned 19166 vs 19165 for the forbidden order).
- Temporal overlap with different interval semantics: half-open welder windows (adjacency allowed) vs buffered closed laydown-slot dates (±2 days rejected, 3 allowed).
- Compensating invariants on different quantities: load add/remove conserves weight; billing approve/void conserves cents (9500000 booked, exactly reversed).
- Caught and fixed during replay: Job auto-COMPLETE required "≥1 billing exists" to avoid vacuous completion at first erection, and priority-8 sub-order was pinned (stale-revision before drawing-approved) to keep the stale-start corner unambiguous.

## Step 3: Copy Shared Files — 2026-08-12T20:31:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T20:45:00.000Z

All checks pass. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_1284_structural_steel_fabricator_erector/workspace/PRD.md`. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

**Output:** `workspace/PRD.md` — 342 lines.

**Section list:**
- §1 Introduction (2 paragraphs: audit-trail business context + segregation-of-duties/derived-state design commitments)
- §2 Global Specifications (9 subsections): 2.1 RBAC, 2.2 Response Structure (byte-identical verbatim block, verified by diff), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Cents/Pounds/Percent precision, 2.7 OCC, 2.8 Validation Ladder & Reference Resolution, 2.9 Cascades & Compound Completion Check
- §3 Business Logic (9 subsections, job-timeline grouping): Job lifecycle → Shop drawings → Mill orders → Sequences & pieces → Welders/welds → Inspections → Shipping loads → Field fixes & backcharges → Progress billing & close-out
- §4 Endpoint Definitions (60-row table, 4 columns, matches scaffold exactly)
- §5 Error Code Catalogue (33 rows, 2 columns)

**Coverage audit (all PASS):**
- Contract 1 field coverage: 71/71 entity+endpoint field names present in backticks; 33/33 error IDs; 7/7 roles; 42/42 state values; all enum values (WEIGHT/COUNT, A36/A572/A992, NOMINAL/ACTUAL, SMAW/FCAW/GMAW, inspection kinds) present.
- Contract 2 rule coverage: validation ladder priorities 1–10 expressed in order with the fixed within-rung-8 ordering; both OCC rules; all 12 state machines' transitions with preconditions + error IDs + side effects; all 8 calculations in reconstructible prose; all applies_to scopes enumerated; sibling branches (NOMINAL/ACTUAL, WEIGHT/COUNT, PASSED/FAILED per kind, ACCEPT/DISPUTE) at equal density.
- Contract 3 §3 path purity: 485 backtick tokens scanned, 0 path/method violations — all §3 endpoint references use state-pair or role+verb framing.

**Notable decisions:**
- *All 12 entities* carry `common_fields: true`, so §2.4 has no exception clause.
- Welders have no GET endpoints in the scaffold — the §4 table faithfully omits them (60 rows).
- `weld_date ≤ clock date` had no explicit error binding in the scaffold; mapped to `ERR_INVALID_REQUEST` (400) as a request-validity rule.
- The AISC-hold gate and `ERR_PIECES_NOT_READY` at ship time were left unordered relative to each other, since the scaffold's priority table assigns no rung to `ERR_PIECES_NOT_READY`.
- Constants embedded in context: 10%/5% whole-amount retainage with the 0.5000 threshold, ±10% mill tolerance (boundary inclusive), 15% backcharge markup, 183-day welder continuity, 2-day closed laydown buffer, hundredweight conversion (÷100).

## Step 5: Generate Unit Tests — 2026-08-12T21:20:00.000Z

All checks pass. Generation complete.

### Summary

**Task:** task_1284_structural_steel_fabricator_erector — full test infrastructure generated from the two design indices only, every test PRD-cited and Design-tagged.

### Test counts
- **Queue A (Difficulty):** 36 tests — all 18 instances × 2 tests each (100% coverage, no skips).
- **Queue B (Corner):** 50 tests — 50 of 52 non-stub instances covered. The 13 `excluded_because:` stubs were not translated (all cross-references verified to resolve to real difficulty instances).
- **Total:** 86 tests, collected cleanly by pytest; all 123 PRD citations verified verbatim against PRD.md via grep; zero skip/xfail markers; zero scaffold references in comments.

### Instances skipped (PRD-first two-condition filter)
1. **Corner/state_machines/weld_ndt_before_visual_rejected** — PRD §3.6 names creation-time state gates only for FINAL_PIECE inspections; for WELD_NDT scheduling on a WELDED weld, a faithful PRD-only reader could defer the rejection to submit time, so creation-time ERR_INVALID_STATE is not uniquely derivable.
2. **Corner/endpoints/delete_line_unknown_piece_not_found** — both path ids (load, piece) resolve; PRD never states the outcome of removing a piece not on the load, and ERR_NOT_FOUND vs ERR_INVALID_STATE are both plausible faithful readings.

### test_helpers/ (9 files)
`/home/ubuntu/github/CodingPRD/tasks/task_1284_structural_steel_fabricator_erector/test_helpers/`
- `types.py` — 15 status/role enums, 12 entity TypedDicts (all common_fields: true)
- `api_client.py` — ApiClient(GenericApiClient) with all 44 endpoints incl. `/_clock/set_current_utc`
- `api_errors.py` — all 33 error IDs + HTTP map, registered with the framework
- `assertions.py` — 12 per-entity assertions (computed fields checked only when the PRD guarantees them, e.g. MillOrder invoice only when RECEIVED)
- `factories.py`, `constants.py` (retainage tiers, 10% mill tolerance, 15% markup, 183-day continuity, 2-day laydown buffer), `test_users.py` (WELDER entity-backed with mandatory `make_welder_headers`), `fixtures.py` (5 tiers: job/drawing lifecycle, fabrication-ready context, piece pipeline to ERECTED via `setup_job_with_pieces`, welder/weld/repair helpers, fix/backcharge/billing helpers), `__init__.py` barrel.

### test_suite/ (11 files)
`conftest.py` + 10 numbered files: 01 envelope/creation defaults, 02 security/segregation, 03 drawing revisions + supersede cascade, 04 job gates + auto-completion, 05 pieces/inspections/rework loop, 06 welding qualification/repair, 07 shipping loads/laydown/AISC hold, 08 mill invoicing + billing creation, 09 percent-complete variants + approve/void currency invariant, 10 field fixes/backcharges/fiscal cap.

Notable design decisions: OCC tests use the sequential replay form (PRD-derivable); the `weld_safety_over_double_booking` second test uses a suspended welder with a genuinely overlapping window (the recipe's nominal overlap was illusory across dates) to truly exercise rung-7-over-rung-9; all expected values copied verbatim from the design indices (e.g. 19166-cent per-line rounding, 120750 cascade amount, 4750000/4491000 tiered nets, 0.7000 vs 0.3333 basis split).

## Step 6: Generate Implementation — 2026-08-12T21:20:00.000Z

Done. The implementation is complete and verified. Summary:

### Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1284_structural_steel_fabricator_erector/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher: guarded `pip install` (skipped when flask importable), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `app.py` | 72 | Entry point, blueprint registration, error handlers (ApiError / 404 / 405 / 500 → envelope) |
| `store.py` | 69 | In-memory store (12 entity dicts + logical clock + insertion seq), `new_record`/`touch` (version++ + updated_at) |
| `errors.py` | 47 | `ApiError` + all 33 error-id constants from the catalog |
| `envelope.py` | 38 | `{meta, response_type, data}` success/error envelopes, pagination meta |
| `validate.py` | 173 | Auth (rung 1), RBAC (rung 2), typed body validators, strict ISO date/datetime parsing, pagination params |
| `domain.py` | 303 | All 8 calculation rules, live job aggregates, supersede/erection cascades, compound completion check |
| `routes/*.py` | 1636 | 13 blueprints covering all 60 routes from the endpoint table |

### Key design decisions

- **State storage**: process-local dicts keyed by UUID, zero seeding at boot. Verified a fresh `bash start.sh` boot returns `total_count: 0` after a prior boot created data.
- **Derived aggregates**: Job's 9 aggregates (except `retainage_releasable_cents`, stored and frozen at completion) are computed **live** from records on every read/use, so they can never drift; `version`/`updated_at` are bumped via `touch()` at every declared side-effect point (piece create/erect, billing create/approve/void, fix approve, settle, transitions, cascade touches).
- **OCC**: `expected_drawing_version` on revise, `expected_job_version` on billing create; checked at ladder rung 5 (before state legality) → 412 `ERR_STALE_VERSION`. Revise bumps the source drawing version; billing create bumps the job version.
- **Validation ladder**: each route explicitly sequences rungs 1→10 (auth → RBAC/WELDER-ownership → path/body FK existence → shape → OCC → state → safety/segregation → referential gates in the PRD's fixed order → constraint/uniqueness → fiscal cap), raising the exact error id/status.
- **Calculations**: `Decimal` + `ROUND_HALF_UP` everywhere; pinned orders honored (per-line labor round → sum → markup round; pct(4dp) → earned → whole-amount retainage rate 0.05 at ≥0.5000 else 0.10 → prior {APPROVED,PAID} sums → net/booked). Integer-exact ±10% mill tolerance (`abs(r-o)*10 <= o`), half-open weld windows, closed 2-day laydown buffer, 183-day continuity (`max prior weld_date >= today-183`, any status).
- **Cascades**: approve-supersede (stale flags skip SHIPPED/ERECTED; stale pieces pulled off loads with LOADING→STAGING fallback), inspection submit/void with per-kind lock rules, erect → sequence auto-ERECTED → compound check (≥1 sequence all ERECTED, ≥1 billing all PAID/VOIDED, all backcharges SETTLED → COMPLETE + retainage_releasable snapshot).

### Boot verification

`bash start.sh` from `./implementation/` binds `0.0.0.0:$PORT`, stays foreground via `exec`, serves first HTTP 200 in ~700 ms, and reboots with an empty store. A 131-check end-to-end smoke run (auth, envelopes, every state machine, every cascade, exact cents math, OCC, pagination, boundary conditions) passes 131/131.

## Step 7: Run Tests and Iterate — 2026-08-12T21:50:00.000Z

Clean 8-round sweep with final artifacts. Summary:

**Iterations run:** 4 sweeps (baseline + 3 after fix batches). Final: **all 8 rounds 86/86 passed, 0 failed, 0 errors**.

**Baseline state:** 77–81/86 per round; union of 14 failing tests across rounds — 5 deterministic test bugs and 9 infra-flake instances (`ConnectionResetError(104)` mid-test; `API server could not be restarted` setup errors under 8-way load).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD rule; the failures were test-artifact bugs or environment flakiness, not coverage/derivability gaps.

**Fixes to `test_helpers/`:**
1. `fixtures.py` — `setup_fabrication_ready()` / `setup_job_with_pieces()` had a kwarg named `start_erection` that shadowed the module-level `start_erection(job_id)` helper, producing `TypeError: 'bool' object is not callable` whenever callers passed `start_erection=True` (root cause of `test_sequence_auto_erected_bubble_up` + `test_job_auto_complete_compound`). Renamed the kwarg to `begin_erection` and updated the two call sites in `test_04_job_gates_and_completion.py`.
2. `api_client.py` — set `Connection: close` on the singleton `ApiClient`'s `requests.Session`. Per-test-server isolation SIGKILLs the server between tests on the same port; urllib3 then reused pooled keep-alive connections to the dead server, yielding `ConnectionResetError(104)` on the next test's first request (e.g. `test_amount_uses_per_line_rounding`, round 2).

**Fixes to `test_suite/`:**
3. `test_07_shipping_loads_and_laydown.py` — `test_add_line_sets_weight_and_flips_loading` and `test_load_weight_exactly_capacity_accepted` asserted HTTP 200 for `POST /shipping-loads/{id}/lines`; PRD §4 verbatim lists "load line" among resource creations returning `201 Created`, and the implementation was PRD-correct. Added `expected_status=201` to both (existing suite convention).
4. `test_09_percent_complete_and_booking.py` — `TestPaidTerminalLockdown` called `self._full_price_billing_submitted()`, which was defined on a different class (`TestBillingBookingInvariant`). Hoisted the helper to a module-level function; all three call sites updated.

**Fixes to `implementation/`:**
5. `start.sh` — replaced the `python3 -c "import flask"` dependency guard (a full interpreter start + flask import, ~450ms idle and seconds under sweep contention, paid twice per boot) with an `importlib.util.find_spec("flask")` probe (~48ms, no flask import), keeping the `pip install` fallback. This halved per-boot latency; round wall time dropped from ~180–195s to ~77–96s and the runner's 15s restart-poll window stopped expiring under 8-way contention. Boot-latency measurement under an 8-way boot storm confirmed p99 = 1.49s after the fix. No application logic changed.

No PRD-required implementation checks were removed or weakened; no endpoints/fields added; no skips/xfails introduced; storage remains in-memory only with a fresh boot per `start.sh` invocation.

## Step 8: Finalize PRD — 2026-08-12T21:55:00.000Z

Verification complete. `PRD_FINALIZED.md` exists as an exact byte-identical copy of `PRD.md` (diff confirms IDENTICAL), and every Step 7 item traced to either a pure test-artifact/launcher fix or behavior the PRD already pins verbatim.

**Line counts / %-delta:** `PRD.md` = 342 lines; `PRD_FINALIZED.md` = 342 lines; delta = 0 lines, 0.0%. `diff` reports the files identical.

**Edits made: 0.** No change bullets to report.

**Per-Step-7-item disposition (pre-edit search log — subjects identified, impl paths enumerated, no wording committed since no edit survived):**

1. **fixtures.py kwarg shadowing (`start_erection` → `begin_erection`)** — (a) Subject: sequence auto-completion and compound job completion. (b) Paths enumerated: `test_helpers/fixtures.py:166,241-253,408-416` (pure Python name-shadowing bug in the helper signature, no API behavior); the unblocked tests quote PRD §3.4 ("if every piece of the piece's sequence now stands in ERECTED, the sequence itself moves from RELEASED to ERECTED") and §3.9 (compound check conditions) verbatim. (c) No wording change — PRD §3.4 line 174 and §3.9 line 237 already pin both behaviors; the fix was test-side only.

2. **api_client.py `Connection: close`** — (a) Subject: HTTP transport between test client and per-test-rebooted server. (b) Paths enumerated: `test_helpers/api_client.py:230-233` — header set on the test-side `requests.Session`; no implementation file is involved (impl never sees or keys off this header). (c) No wording change — no PRD-visible behavior.

3. **test_07 load-line status 200 → 201** — (a) Subject: HTTP status for `POST /shipping-loads/{id}/lines`. (b) Paths enumerated: `implementation/routes/loads.py:109-141` — `add_line` ends with `return ok_object(view(load), 201)`; the only other load-line endpoint, `remove_line` (loads.py:144-160), is a DELETE returning 200, consistent with PRD §4's create-vs-modify split; all sibling creation endpoints likewise return 201. (c) No wording change — PRD §4 line 241 already lists "load line" verbatim among creations returning `201 Created`; the implementation was PRD-correct and the test was the bug.

4. **test_09 helper hoist (`_full_price_billing_submitted` to module level)** — (a) Subject: PAID-terminal lockdown (void from PAID rejected, billing stays PAID). (b) Paths enumerated: `test_suite/test_09_percent_complete_and_booking.py:24,124-152`; impl billing void transition guarded by from-state `APPROVED`. (c) No wording change — PRD §3.9 ("Both `PAID` and `VOIDED` are terminal") plus §2.8 rung 6 (`ERR_INVALID_STATE`, HTTP 409) already pin the behavior; the fix was a test-class scoping bug.

5. **start.sh `find_spec` boot probe** — (a) Subject: launcher dependency-check mechanics. (b) Paths enumerated: `implementation/start.sh:8-10` — probe swap only; `app.py`, `domain.py`, and all route modules untouched; Step 7 explicitly notes "No application logic changed." (c) No wording change — the PRD specifies API behavior, not launcher internals.

Per the task instructions, when no Step 7 item reveals a PRD silence or PRD/impl mismatch, the correct output is `PRD_FINALIZED.md` as an exact copy of `PRD.md` — which is what was produced at `workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-12T22:05:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1284_structural_steel_fabricator_erector/workspace/PRD_COMPLETED.md` with 13 inline edits and zero structural changes.

**Stats**
- Source `PRD_FINALIZED.md`: 342 lines, 50,629 chars → `PRD_COMPLETED.md`: 342 lines, 51,938 chars (char-delta +1,309; all edits in-paragraph, no lines added/removed, no new sections).
- Counts: 11 ambiguity-pins, 2 mismatch-revisions.

**Changes (one per bullet)**
- §2.3 Pagination — insert — ambiguity — pinned `limit`>100 clamps to 100 while `limit`<1, negative `offset`, or non-integer values fail `ERR_INVALID_REQUEST` (400) — implementation/validate.py:151-173.
- §2.3 Pagination — insert — ambiguity — pinned `created_at` sort ties break by creation order (earlier-created first) — implementation/store.py:67-69.
- §2.4 Common Resource Properties — insert — ambiguity — pinned `version` starts at 1 on creation (matters for both OCC tokens) — implementation/store.py:45-53.
- §2.8 rung 4 (Request shape) — insert — ambiguity — added three ladder members impl raises at rung 4: non-JSON-object body, negative `settled_amount_cents`, and future `weld_date` — implementation/validate.py:47-53, routes/backcharges.py:74-76, routes/welds.py:71-75.
- §2.8 rung 8 (Referential gates) — insert — ambiguity — added load readiness at shipment (`ERR_PIECES_NOT_READY`), which the ladder previously omitted entirely though impl evaluates it at rung 8 (after the rung-7 AISC hold) — implementation/routes/loads.py:185-192.
- §2.9 Cascades — revise — mismatch — job terminal state spelled `COMPLETE` (was `COMPLETED`), matching impl and §3.1/§3.9 — implementation/domain.py:301.
- §3.1 Jobs — revise — mismatch — "nine computed aggregates" → "eight" (impl's job view exposes exactly the eight the paragraph then enumerates: 7 derived live + stored `retainage_releasable_cents`) — implementation/domain.py:96-108.
- §3.3 Mill Orders — insert — ambiguity — a placed order opens with `received_weight_lbs` and `invoice_amount_cents` null until receive — implementation/routes/mill_orders.py:61-62.
- §3.5 Welds — insert — ambiguity — pinned that a future `weld_date` fails as `ERR_INVALID_REQUEST` (HTTP 400) (PRD stated the rule in §2.5/§3.5 without an error code) — implementation/routes/welds.py:71-75.
- §3.6 Inspections — insert — ambiguity — pinned that submitting an outcome whose dependent record no longer stands in the stated from-state still records the outcome and leaves the dependent unchanged (no rejection) — implementation/routes/inspections.py:159-178.
- §3.7 Shipping Loads — insert — ambiguity — adding a piece whose `load_id` is already set fails with `ERR_INVALID_STATE` — implementation/routes/loads.py:126-127.
- §3.7 Shipping Loads — insert — ambiguity — both line add and line remove return the updated load object in `data` — implementation/routes/loads.py:141,160.
- §3.8 Field Fixes — insert — ambiguity — a reported fix opens in `PRICED` with `amount_cents` null until approval prices it — implementation/routes/fixes.py:90.
- §3.8 Backcharges — insert — ambiguity — `settled_amount_cents` must be a non-negative integer, else `ERR_INVALID_REQUEST` (400) — implementation/routes/backcharges.py:74-76.

**Verification notes**: every endpoint, role set, state transition, cascade hop, rounding order (mill invoice, backcharge markup, billing snapshot), tolerance/window/continuity arithmetic, and ladder ordering in `implementation/` was walked against the PRD; everything not listed above already matched uniquely (including OCC token placement at rung 5, AISC-hold before readiness at ship, half-open weld-window overlap, ±10% closed mill tolerance, and the compound completion check's exact four conditions).
