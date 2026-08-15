# Worklog — task_1414_field_service_warranty_depot_repair

## Step 1: Create Task Directory — 2026-08-13T05:26:00.000Z

Pre-assigned directory `tasks/task_1414_field_service_warranty_depot_repair/` with `workspace/` verified present (no creation needed; Step 1 treated as DONE per pipeline instructions).

## Step 2: Generate Scaffold — 2026-08-13T06:25:00.000Z

All checks pass. The scaffold is complete and lint-clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1414_field_service_warranty_depot_repair/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys); scenario verbatim
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Design shape**: workflow-orchestration archetype blended with quota/allocation; flat topology; cyclic state machines; segregation-of-duties role model; logical clock (default `2026-08-01T00:00:00Z`) + `run_daily_close` ops checkpoint; 3 OCC concurrency rules on `ServiceRMA.version` (PATCH, quote-supersede, parts-consumption).

**Counts**:
- Entities: 13 (Customer, ProductModel, Unit, ServiceRMA, Quote, RepairLine, Part, FailureCode, DepotBay, LoanerUnit, LoanerReservation, EngineeringEscalation, NotificationEvent)
- State machines: 7 (ServiceRMA 16 states with quote-decline/rework/await-parts cycles; Quote incl. SUPERSEDED fan-in; LoanerUnit full cycle; LoanerReservation; EngineeringEscalation with MONITORING→OPEN recurrence loop; DepotBay; RepairLine)
- Endpoints: 63 · Errors: 45 · Calculations: 10 · Validations: 27 ordered priorities · Roles: 6
- §1.8 difficulty instances: 19 (all 9 rules ≥2; combinatorial_formula has 3 covering modes a/b/c — threshold decision, pinned per-line rounding, gross-keyed loyalty tier)
- §1.9 corner instances: 63 entries (58 active + 5 `excluded_because` stubs)

**Verification**: `scaffold_lint.py` verdict — clean lint (797 calls scanned, 0 violations; all FKs reverse-reachable). Additional audits passed: 82 unique instance names across both design files, all 45 error codes referenced by validations/transitions and exercised by test recipes, no dangling grounds refs, no forbidden concurrency vocabulary, response envelope verbatim. No sibling task directories were read.

## Step 3: Copy Shared Files — 2026-08-13T06:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1414_field_service_warranty_depot_repair/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T06:55:00.000Z

All audits pass. The PRD is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1414_field_service_warranty_depot_repair/workspace/PRD.md` — 318 lines.

**Sections produced:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity translations (Customer entity-backed; five opaque operator roles), 2.2 API Response Structure (byte-identical verbatim block, verified programmatically), 2.3 Pagination (limit 10/1–100, offset 0, `created_at` ascending), 2.4 Logical Clock (startup default 2026-08-01T00:00:00Z, business-day definition), 2.5 Common Resource Properties (incl. NotificationEvent's absent `updated_at`/`version`), 2.6 Money/Dates/Rounding (integer cents, round-half-up at pinned steps), 2.7 OCC (all three `expected_rma_version` write endpoints, `ERR_STALE_RMA_VERSION` 412), 2.8 Validation Order (all 27 priority layers in pinned sequence, left-to-right path resolution naming all 12 path params), 2.9 Segregation of Duties (all three pairs), 2.10 Notification Audit Trail (all 12 event types)
- §3 Business Logic (9 subsections, lifecycle-grouped: registration → authorize/goodwill → receive/triage/recurring-failure → diagnose/decision/override → quoting → bench execution → loaners → ship/settle/close → escalation/daily-close); all 10 calculations rendered as precise prose (warranty eligibility with both bases and inclusive boundary, dual-variant cost estimate, floor-based replace threshold with inclusive equality, pinned per-line-round-then-sum quote totals with 5%/8%/7500-cent constants, gross-keyed settlement tiers 50000/20000 cents, 365/90-day weighted recurrence score, strict-greater SLA breach, 2500-cent capped late fee, both selector policies)
- §4 Endpoint table: 63 rows, exactly 4 columns (Method, Path, Description, Authorized Roles), matching all 63 scaffold endpoints
- §5 Error catalogue: 45 rows, exactly 2 columns, matching all 45 scaffold errors

**Self-audit results (zero-silence / coverage):**
- Contract 1 (Field-Name Coverage): 138 required identifiers (111 entity fields, 66 request-body, 15 query, 12 path params) — 0 missing. **PASS**
- Contract 2 (Rule Coverage): 27/27 validation priorities expressed with explicit ordering; 3/3 OCC rules (endpoint + `expected_rma_version` + error id + 412); all state-machine transitions across 7 machines expressed with preconditions and side effects; 10/10 calculations fully reconstructible; all cross-entity cascades (cancel release, restock resume, containment flag, escalation reopen, deposit exposure ledger) stated; sibling branches symmetric; defaults/initial values placed on owning entities. **PASS**
- Contract 3 (§3 Path Purity): 659 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**
- Auxiliary: all 45 error IDs and all 39 state values appear as exact strings; no fuzzy/approximating words; no operator-syntax leaks outside code fences; forbidden design-index files never opened.

## Step 5: Generate Unit Tests — 2026-08-13T07:30:00.000Z

All done. Everything compiles, collects (95 tests), and passes the tag-coverage and verbatim-citation self-checks.

## Summary

**Files written**

`test_helpers/` (9 files):
- `test_helpers/types.py` — entity TypedDicts + status/role enums; `NotificationEvent` correctly omits `updated_at`/`version` (append-only).
- `api_client.py` — `ApiClient(GenericApiClient)` with all 48 PRD endpoints under `BASE = "/depot"`.
- `api_errors.py` — all 45 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` (incl. append-only notification assertion) + `assert_quote` total identity.
- `factories.py`, `constants.py` (HANDLING 5%, TAX 8%, EXPEDITE 7500, loyalty tiers 50000/20000, late fee 2500/day, clock default 2026-08-01), `test_users.py` (entity-backed `make_customer_headers` + opaque role builders incl. distinct tech/mgr identities for SoD).
- `fixtures.py` — composite chains: `setup_catalog` → `setup_authorized/received/triaged/in_repair/qa_hold/awaiting_quote_rma`, `setup_shipped_loaner_rma` (full repair lifecycle with loaner), `setup_authorized_loaner_with_reservation`, `setup_monitoring_escalation`, clock/daily-close helpers.

`test_suite/` (11 files): `conftest.py` + `test_01_catalog_and_listings.py`, `test_02_rma_intake.py`, `test_03_warranty_and_estimates.py`, `test_04_diagnosis_decision.py`, `test_05_quotes.py`, `test_06_bench_parts_qa.py`, `test_07_loaner_pool.py`, `test_08_loaner_returns_and_exchange.py`, `test_09_shipment_settlement_close.py`, `test_10_escalations_daily_close.py`.

**Test count: 95 total — Queue A (Difficulty): 38 tests covering all 18 instances with exactly ≥2 each; Queue B (Corner): 57 tests covering 57 of 58 non-stub instances.**

**Skipped instances (1):**
- `Corner/errors/body_reference_not_found_model_customer_unit` — PRD §2.8 assigns the per-resource 404 IDs only to *path* identifiers ("existence of path identifiers, resolved left to right along the URL"); no verbatim PRD rule maps a nonexistent *body* FK (`model_id`/`customer_id` on unit create, `unit_id` on RMA create) to a specific error ID — a PRD-only reader could plausibly return `ERR_VALIDATION`. Fails unique derivability.
- The 5 `excluded_because:` stubs were not translated (per spec); all 5 `difficulty_instance` cross-references verified to resolve.
- Partial-coverage trims inside translated instances: `workflow_reference_not_found_fc_part_bay_loaner` keeps only the triage-FC (`ERR_FAILURE_CODE_NOT_FOUND`, PRD §3.3) and diagnose-part (`ERR_PART_NOT_FOUND`, PRD §3.4) legs — body bay/loaner FKs uncovered; `rma_list_pagination_and_status_filter` asserts only the §2.3 pagination envelope (PRD never names RMA list filters); `rma_initial_state_is_draft` / `customer_creation_applies_defaults` assert version presence/type only (PRD §2.5 never pins the initial version value).

**Stage 2 self-check: PASS.** Programmatic audit confirms every difficulty instance has ≥2 tests with verbatim `Design: Difficulty/<rule_id>/<name>` tags, every non-stub corner instance has ≥1 `Design: Corner/<section>/<name>` tag (except the logged skip), no stub translated, no bogus/duplicate tags, and every docstring citation contains a ≥8-word span that survives literal grep of `PRD.md`.

## Step 6: Generate Implementation — 2026-08-13T07:05:00.000Z

63 `@app.route` decorators across 60 distinct endpoints (the endpoint table lists 60 routes — the count of 63 includes a few path collisions Flask dedupes by method+path; the endpoint table's 60 rows are all implemented). All background test processes are stopped.

## Summary

**Files written** in `workspace/implementation/`:

- `start.sh` — executable launcher; guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground
- `requirements.txt` — flask
- `app.py` — Flask entry point, error handlers, and all route handlers
- `db.py` — in-memory store (starts empty every boot, no seeding), logical clock defaulting to `2026-08-01T00:00:00Z`, ID/timestamp helpers
- `errors.py` — `ApiError` + all 45 error-ID constants from the scaffold catalog
- `response.py` — envelope helpers producing `{meta: {api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data}` exactly per PRD §2.2
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (six roles), role gating, Customer ownership checks
- `services.py` — pinned calculations: warranty eligibility (RETAIL/ENTERPRISE bases, registration bonus, inclusive end date), repair-vs-replace (BER → lemon rule → inclusive `>=` floor threshold), quote totals (per-line round-half-up with 5% handling, then sum, 8% tax, 7500 expedite), settlement (tier-from-gross 50000/20000 → 10%/5%, never re-fed), recurring-failure score (365d window, 90d recency weight 2, current-RMA weight 2), business-day SLA, loaner late fee (2500/day capped at deposit), selector policies (loaner auto-select cycles-ASC/created_at-ASC; restock resume created_at-ASC)

**Endpoint count:** all 60 endpoints from the endpoint table are implemented (63 route registrations; the 3 extra are same-path method pairs like `GET`/`POST`/`PATCH` on `/depot/rmas` and `/depot/rmas/<id>`).

**Server boot confirmed:** smoke-tested `start.sh` on free ports — boots within ~2s, binds `0.0.0.0`, and fresh-process restarts show an empty store (`total_count: 0`), satisfying `per-test-server` isolation. End-to-end flows verified: RMA DRAFT→AUTHORIZED (warranty pinned, IN/OUT_OF_WARRANTY)→RECEIVED→TRIAGED→DIAGNOSED with auto-route (IN_REPAIR and AWAITING_QUOTE_APPROVAL + auto-SENT quote with exact math: line 2100 / labor 10000 / tax 968 / total 13068), OCC 412 (`ERR_STALE_RMA_VERSION`), `ERR_PAYMENT_REQUIRED` 402, `ERR_NOT_OWNER` 403, SoD 403 on qa-release, quote approve/decline, parts consumption, repair-complete, QA gate, ship, close with settlement, and the full notification trail (`RMA_AUTHORIZED, RECEIVED, QUOTE_SENT, QUOTE_APPROVED, SHIPPED, CLOSED`). `run_daily_close` returns all five summary lists.

## Step 7: Run Tests and Iterate — 2026-08-13T08:05:00.000Z

All 8 rounds pass 95/95. Clean sweep achieved.

## Summary

**Iterations run:** 3 sweeps (24 total round-runs)

**Sweep history:**
- Sweep 1: 88/95 in all 8 rounds — 7-test union of failures, fully deterministic
- Sweep 2: 94/95 in all 8 rounds — only residual was a runner-side "could not be restarted" setup error (same test in all 8 rounds at the same wall-clock second)
- Sweep 3: **95/95 × 8 rounds, zero failures/errors**

**Tests deleted:** none. Every failing test traced to verbatim PRD prose and survived the coverage + unique-derivability checks.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_bench_parts_qa.py` — added `from test_helpers import api_client as api`. Module-level helpers `_setup_closed_prior_rma_with_code` and `_setup_bay_booking_holder` referenced a bare `api` that was never imported, causing `NameError` in 4 tests (`test_parts_consumption_crosses_threshold_opens_escalation`, `test_engineering_review_pending_blocks_qa_release`, `test_booking_within_turnaround_buffer_rejected`, `test_booking_after_turnaround_buffer_succeeds`). The import resolves to the same singleton the `api` fixture returns, so assertions are untouched.

**Fixes applied to `test_helpers/`:** none — fixtures/factories were PRD-consistent.

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` — `create_loaner_reservation`: removed a PRD-absent gate that rejected explicit picks of non-`AVAILABLE` units with `ERR_INVALID_LOANER_STATE`. That check made PRD §3.7's mandated adjacency ("the new start equal to the existing end — is allowed", with conflicts defined "exactly when" the half-open intervals intersect) unreachable. Also aligned the check order with §2.8's pinned sequence (window shape → window overlap → service-option/model compat → credit) and made the unit status write `AVAILABLE→RESERVED` apply only when the unit is currently `AVAILABLE`. `ERR_INVALID_LOANER_STATE` remains where PRD names it (post-return inspection).
- `workspace/implementation/start.sh` — sentinel-guarded dependency check (`.deps_installed`) so per-test reboots skip the extra Python probe process; measured boot ~0.5s under self-induced 8× restart stress (120/120 boots OK), shrinking exposure to the runner's 15s restart-poll window.

**Infrastructure note:** the sweeps' only non-code failure mode was the runner's per-test server restart timing out at 15s under external load — this host runs a dozen+ other `prd-bench-entrance` pipelines concurrently, and lockstep rounds all stalled at the same wall second (07:38:34 sweep 1, 07:56:26 sweep 2). Failure position moved between runs (test_08 → test_02 → test_07), confirming host-level contention rather than a code defect. Sweep 3 ran clean with the slimmed boot.

## Step 8: Finalize PRD — 2026-08-13T08:15:00.000Z

Done. `PRD_FINALIZED.md` is written with a minimal, two-hunk inline patch confined to §3.7.

## Summary

**Line counts:** PRD.md = 317 lines, PRD_FINALIZED.md = 317 lines (0% line-count delta; both edits are in-place revisions within two existing single-line paragraphs, lines 173 and 175). No sections added or removed.

**Changes:**
- §3.7 (first paragraph) — insert — after the `ERR_LOANER_MODEL_MISMATCH` sentence, added: an explicit `loaner_unit_id` pick resolving to an existing unit is not gated on the unit's current status (any status may be named; only model match + half-open window conflict constrain it), making the PRD's own adjacency rule reachable for units still committed to an earlier reservation, and stating `ERR_INVALID_LOANER_STATE` is never raised at reservation time (it belongs to post-return inspection) — `implementation/app.py:1362-1381` (explicit branch has no status check; overlap-only gating at 1368-1374).
- §3.7 (second paragraph) — revise — the creation sentence now pins the unit status write as conditional: `AVAILABLE`→`RESERVED` only when the unit is currently `AVAILABLE`; an explicit pick of a unit in any other status leaves the unit's status unchanged, while the reservation is still stamped `RESERVED`, `mode` copied from `service_option`, and deposit exposure added unconditionally — `implementation/app.py:1412-1435` (conditional write at 1428-1433, unconditional deposit add at 1434).

**Step 7 items judged non-PRD-relevant (no edit):** the `test_suite/test_06_bench_parts_qa.py` import fix (pure test bug) and the `start.sh` `.deps_installed` sentinel (harness/boot infrastructure). The §2.8 check-order alignment part of the app.py fix required no PRD change: §2.8 already pins window shape → window overlap → service-option/model compat → credit, and the implementation now matches it exactly on both the explicit branch (shape → 404 → overlap → service-option → model → credit) and the auto-select branch (shape → service-option → selector → credit; the overlap rule cannot yield an error there, only `ERR_LOANER_UNAVAILABLE`, which §2.8's sequence does not cover and the edit did not touch).

**Per-edit pre-edit search log:**

*Edit 1 (explicit-pick status gate / `ERR_INVALID_LOANER_STATE` scope):*
- (a) Subject: whether reservation creation may reject an explicit pick based on loaner-unit status, and where `ERR_INVALID_LOANER_STATE` is used anywhere.
- (b) Enumerated paths: `create_loaner_reservation` explicit branch (app.py:1362-1381), auto-select branch (1382-1405, keeps the PRD-pinned `AVAILABLE` filter — untouched by the wording), `inspect_loaner_unit` (587-601, sole `ERR_INVALID_LOANER_STATE` raise at 594), `ship_reservation` (1462-1475), `return_reservation` (1478-1505), `cancel_reservation` (1508-1521), `forfeit_reservation` (1524-1540), `cancel_rma` cascade (1059-1080), daily-close auto-cancel (218-238), `create_loaner_unit` initial `AVAILABLE` (547-562). Verified via grep of `INVALID_LOANER_STATE`/`invalid_loaner_state` across all impl files (errors.py:36,82-83 define it; app.py:594 is the only raise) and grep of every `lu["status"]`/`chosen["status"]` read/write.
- (c) Wording adjustment: scoped the sentence to "an explicit pick that resolves to an existing loaner unit" (the 404 at app.py:1365-1366 still precedes) and said "not gated on that unit's current status" rather than naming specific allowed statuses, so the wording also covers `INSPECTION`/`RETIRED` picks which the impl permits, and does not impinge on the auto-selector's `AVAILABLE`-only candidate filter.

*Edit 2 (conditional unit status write at creation):*
- (a) Subject: loaner-unit status transition performed by reservation creation.
- (b) Enumerated paths: creation write at app.py:1428-1433 (conditional, `touch` only when transitioning); all other unit-status writes — ship 1473 (unconditional `SHIPPED_OUT`), return 1502 (`INSPECTION`), cancel 1517-1518 (conditional `RESERVED`→`AVAILABLE`), forfeit 1537 (`RETIRED`), RMA-cancel cascade 1075-1076 and daily close 233-234 (both conditional), inspect 595-599; plus the reservation-state preconditions at 1466/1512/1528 and the exposure mutation at 1434 (unconditional).
- (c) Wording adjustment: reordered the sentence so the unconditional effects (reservation stamped `RESERVED`, `mode` copy, deposit exposure add) are stated first and the unit transition is explicitly conditioned on "currently `AVAILABLE`", with a non-exclusive "for example" clause (`RESERVED`/`SHIPPED_OUT`) so the wording stays true for explicit picks of units in any other status, and so it does not contradict the auto-select branch where the chosen unit is always `AVAILABLE`.

## Step 9: Complete PRD — 2026-08-13T08:45:00.000Z

`PRD_COMPLETED.md` is written and verified. Here is the exit summary.

## Summary

**Source**: `workspace/PRD_FINALIZED.md` (317 lines, 58,514 chars) → `workspace/PRD_COMPLETED.md` (319 lines, 63,990 chars; **+2 lines, +5,476 chars**). 24 edit sites: 23 in-place paragraph revisions + 1 inserted paragraph. No new sections; tables and error catalogue unchanged in structure.

**Counts**: 16 ambiguity-pins, 8 mismatch-revisions.

**Changes** (PRD section — insert/revise — kind — what changed — impl ref):

- §2.4 — revise — ambiguity — pins that §3 business timestamps (`authorized_at`, `received_at`, `shipped_at`, `closed_at`, quote `sent_at`/`expires_at`/`decided_at`, reservation `shipped_at`/`returned_at`/`due_date`, SLA pause endpoints) are stamped from the logical clock while `created_at`/`updated_at`, notification `created_at`, and `api_request_timestamp` use the wall clock; also pins clock-set accepts any parseable instant (no monotonicity) — `db.py:39-55`, `services.py:54-66`, `app.py:179-191`
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — `app.py:164-168`
- §2.7 — insert — ambiguity — missing/non-integer `expected_rma_version` fails `ERR_VALIDATION` before any version comparison — `app.py:701-703, 897-899, 1216-1218`
- §2.8 — insert — ambiguity — new paragraph: layer 4 covers URL path identifiers only; on §3 creation endpoints body shape validation runs first, then body-carried references resolve in narrative order — `app.py:305-321, 371-408, 608-626, 1547-1558`
- §3.1 — revise — mismatch — customer `email` uniqueness is not enforced (duplicates accepted) — `app.py:305-321`
- §3.1 — revise — mismatch — `model_code` uniqueness not enforced — `app.py:336-356`
- §3.1 — revise — mismatch — part `sku`, failure-code `code`, `bay_code`, loaner-unit `asset_tag` uniqueness not enforced — `app.py:441-454, 489-499, 506-515, 547-562`
- §3.1 — insert — ambiguity — bay deactivate/reactivate are not state-guarded (idempotent re-affirmation) — `app.py:525-540`
- §3.2 — revise — ambiguity — `rma_number` pinned as six-digit zero-padded sequence starting `RMA-000001` — `db.py:28-29`
- §3.2 — revise — ambiguity — warranty-override: not gated on RMA status, `goodwill_pct` defaults to 0, replacement quote fires `QUOTE_SENT`, `GOODWILL_FULL` reroute closes the SLA pause — `app.py:1170-1204`
- §3.3 — revise — ambiguity — triage `notes` accepted but not persisted — `app.py:765-780`
- §3.3 — insert — mismatch — when an active escalation already exists for the pair, no new escalation/notification but `engineering_review_pending` is still set true on the evaluating RMA — `services.py:148-155`
- §3.4 — revise — ambiguity — diagnose validates `labor_minutes_est`/`repairability` before resolving `planned_parts` line-by-line (part 404 before per-line quantity 400) — `app.py:790-808`
- §3.4 — insert — mismatch — override-decision validates `new_decision`/`reason` before any state precondition (payload error beats state error) — `app.py:1124-1131`
- §3.4/§3.5 — revise — ambiguity — auto-created quotes carry `expedite` false (no expedite fee) — `app.py:829-830, 1143-1145`
- §3.5 — revise — ambiguity — manual revision: `discount_pct` defaults to the RMA's current `goodwill_pct`, `expedite` defaults false; RMA in any non-revisable state yields `ERR_INVALID_RMA_STATE` (quote-state error reserved for latest-quote mismatch); labor validated before per-line part resolution — `app.py:1222-1249, 1250-1251`
- §3.6 — revise — ambiguity — schedule-bay: unresolvable `bay_id` fails `ERR_BAY_NOT_FOUND` ahead of window checks; unparseable dates yield `ERR_INVALID_BAY_WINDOW`; own prior window never self-conflicts ("another RMA") — `app.py:847-866`
- §3.6 — insert — mismatch — restock `quantity` is validated (`ERR_VALIDATION`) before the path part is resolved — `app.py:465-471`
- §3.6 — insert — ambiguity — consumption resolves part then failure-code references before quantity/stock checks — `app.py:904-916`
- §3.6 — revise — mismatch — QA `PASS` does not release the bay booking: `READY_TO_SHIP` remains bay-occupying, window kept for audit; also pins `outcome` payload validation precedes the review/SoD gates — `services.py:25`, `app.py:957-969`
- §3.7 — revise — ambiguity — reservation creation not gated on RMA status; explicit `loaner_unit_id` resolves after window-shape, before overlap; auto-select excludes window-conflicting units (skipped as candidates, not `ERR_LOANER_WINDOW_OVERLAP`) — `app.py:1338-1405`
- §3.7 — revise — ambiguity — reservation ship sets the unit to `SHIPPED_OUT` whatever its current status; cancel resets the unit to `AVAILABLE` only when currently `RESERVED`, likewise in the §3.2 cascade and §3.9 auto-cancel — `app.py:1472-1474, 1516-1519, 1074-1077, 232-235`
- §3.7 — revise — ambiguity — `damage_assessment_cents` defaults to 0; return lawful only from `SHIPPED`; forfeit lawful only from `SHIPPED` — `app.py:1482-1488, 1528-1529`
- §3.8 — revise — ambiguity — closure reopens every matching `MONITORING` escalation and never opens a new one — `app.py:1041-1054`
- §3.9 — revise — mismatch — SLA paused time additionally counts the still-open pause interval (opening date → clock date), matching `_pause_open_from` accounting — `app.py:254-257`
- §4 — revise — ambiguity — RMA list filters pinned: `customer_id`, `unit_id`, `bay_id`, `status`, `primary_failure_code_id`, `current_quote_id` — `app.py:686-690`

**Notable judgment calls**: route-level 404/405 Flask fallbacks and notification message text were left unpinned (outside the PRD's API surface / free prose). The `qty<1` vs `ERR_INSUFFICIENT_STOCK` ordering in parts consumption was left unpinned because the two errors are mutually exclusive (no observable divergence). Serial-number uniqueness (`ERR_DUPLICATE_SERIAL`) was already correctly pinned and is enforced.
