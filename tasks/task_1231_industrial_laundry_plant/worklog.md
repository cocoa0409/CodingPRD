## Step 1: Create task directory — 2026-08-12T03:26:59.820Z

Task directory pre-assigned as `tasks/task_1231_industrial_laundry_plant` with `workspace/` subdirectory already present. Step 1 treated as done; no auto-index scan run.

## Step 2: Generate scaffold — 2026-08-12T04:09:06.314Z

All three files exist, lint is clean, and every checklist item verified. 

## Summary

Generated the scaffold for **task_1231_industrial_laundry_plant** at `/home/ubuntu/github/CodingPRD/tasks/task_1231_industrial_laundry_plant/`, designed harder than expert level (exceeds every Expert band in §0.4).

**Design**: workflow-orchestration + ledger-reconciliation archetype over the full soil-to-clean linen pipeline. Key difficulty drivers:
- **Dual-variant calcs in two domains**: COG billing (actual FINISHED loads vs preview including in-flight loads — 6000 vs 12000 cents on identical plant state) and utility surcharge (trailing-3-month estimated vs same-month actual true-up — 10000 vs 12000 cents).
- **Combinatorial formulas in modes (a) and (b)**: tiered utility surcharge with nested min/max across three pass-through brackets (excess 150000 → tiered 87500 → 43750 after 50% share), and COG rounding with pinned order round-per-category-then-discount (485971 vs forbidden-order 485970 — 1-cent divergence, computed and verified in Python).
- **Cyclic state machines on two entities**: WashLoad rewash loop (FAIL → REWASH_PENDING → RUNNING, formula escalation WF_STANDARD→WF_HEAVY_SOIL, MAX_REWASH_COUNT=2) and Garment 6-state chip round-trip driven entirely by cross-entity cascades.
- **Transitive cascades**: apply-credit (Discrepancy→Invoice→Customer balance, depth 3) and hygienic-fail-to-delivery-dispute (depth 3, different trigger).
- **Priority conflicts on different category pairs**: state-vs-fiscal (invoice issue), safety-vs-referential (test bypass vs category-in-batch).
- **Boundary precision on different metrics/endpoints**: reject-rate >= threshold at exactly 25.00% (sort lock) vs par shortfall at exactly 5 pieces (mark-delivered).
- **Temporal overlap with different interval semantics**: wash machine half-open [start,end) adjacency allowed vs finish line closed interval with ±10 min buffer.
- **Compensating invariants on different quantities**: piece conservation (batch void) and money conservation (issue↔pay round-trip on Customer.account_balance_cents).
- **OCC** on Customer.version for invoice issue and mark-delivered (412 ERR_STALE_VERSION).

**Counts**: 16 entities, 11 state machines, 14 calculations, 13 validations, 91 endpoints, 38 error codes, 6 roles, 2 concurrency rules. §1.8: 9 rule blocks / 18 difficulty instances. §1.9: 9 sections / 42 corner instances. 837 structured calls across both design files.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**File sizes**: SCAFFOLD.yaml 87,773 B; SCAFFOLD_DIFFICULTY_DESIGN.yaml 96,611 B; SCAFFOLD_CORNER_DESIGN.yaml 106,999 B.

Notable iteration: the lint's FK reverse-reachability check (f) mandates a flat/sub-resource URL layout (`<parent-collection>/{id}/<children>` with literal `{id}`), so I flattened the initially nested `/plants/{plantId}/...` URL space across all three files, added reverse-reachability GETs for all 24 FK edges, pinned the estimated-surcharge formula determinism (plant_ref_clean_lbs from latest trailing reading), and verified every formula-derived assert literal by executing the formulas in Python (two values were corrected as a result: preview 10800→12000, trailing-month readings re-pinned).

## Step 3: Copy shared files — 2026-08-12T04:09:31.943Z

Copied `./INSTRUCTION.md` to `tasks/task_1231_industrial_laundry_plant/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T04:20:43.440Z

The PRD is complete and verified. `/home/ubuntu/github/CodingPRD/tasks/task_1231_industrial_laundry_plant/workspace/PRD.md` exists on disk (380 lines, 8,262 words).

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1231_industrial_laundry_plant/workspace/PRD.md` — 380 lines, 8,262 words. Neither withheld file (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) was opened, and no other task directory was inspected.

**Section list**:
- 1. Introduction (2 paragraphs)
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (fixed block emitted verbatim); 2.3 Pagination; 2.4 Resource Identity, Timestamps, and Versioning; 2.5 The Logical Plant Clock; 2.6 Units, Precision, and Rounding; 2.7 Optimistic Concurrency Control; 2.8 Machine and Line Scheduling Discipline; 2.9 Validation Pipeline and Check Ordering; 2.10 Resource Hierarchy and Nested Retrieval
- 3. Business Logic & Workflows — 3.1 Plant Configuration, Customer Enrollment, and the Linen Catalog; 3.2 Route Planning, Dispatch, and Soiled Pickup; 3.3 Receiving, Sorting, Classification, and Reject Alerts; 3.4 Wash Operations, Hygienic Testing, and Rewash Escalation; 3.5 Finishing Lines, Throughput, and Linen Loss; 3.6 Garment Chip Tracking and Lost-Item Charges; 3.7 Deliveries, Shortages, and Discrepancy Settlement; 3.8 Billing, Utility Surcharge, and Customer Credit
- 4. Endpoint Definitions (4-column table, all 91 endpoints, role columns verified byte-equal to scaffold)
- 5. Error Code Catalogue (2-column table, all 38 error IDs)

**Coverage audit**:
- **Contract 1 (Field-Name Coverage): PASS** — 89 required names (16 entities' fields incl. common fields, every endpoint input/query param incl. `carts`, `to_iso8601`, `outcome`, `invoice_id`, `expected_customer_version`, `override_par_pieces`, nested `cart_tag`/`scale_weight_lb`): 89 present, 0 missing (verified mechanically with fenced code blocks stripped before token extraction).
- **Contract 2 (Rule Coverage): PASS** — 13 priority-ordered validations expressed as an explicit ordered pipeline in §2.9 with applies-to scopes; both OCC rules (invoice issue, delivery mark-delivered) named with `expected_customer_version` + `ERR_STALE_VERSION`/412; all 51 state-machine transitions across 11 machines rendered with preconditions, error IDs, and side-effect cascades (chip cascades, cart `RECEIVED→SORTED` on post, par decrement on post, stop auto-close/dispute, delivery auto-settle, credit application triple-mutation, invoice void queue release); all 14 calculations expressed as reconstructible prose (tiered COG with pinned per-category rounding order, rental 2% piece-day, utility surcharge actual/estimated variants with 100000/500000-cent tiers at 50/75/100%, 4-decimal share, 3-month trailing window, true-up/delta-only invoice, rewash ladder and ceiling of 2, 60% credit rate, 10-minute buffered closed line intervals vs half-open machine intervals, floor-zero invoice total); 98/98 scripted rule markers present; sibling branches (PASS/FAIL, ACCEPTED/REJECTED, three mark-lost source states, both OCC endpoints) given equal density.
- **Contract 3 (§3 Path Purity): PASS** — 444 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos.
- All 48 state values, all enum values (customer kinds, billing modes, wash formulas, dispositions, reject reasons, test results), and all 38 error IDs appear verbatim in prose.

## Step 5: Generate unit tests — 2026-08-12T04:51:25.710Z

Generation complete. Summary:

## Helper files written (`test_helpers/`, 9 files)
- `types.py` — 16 entity TypedDicts + 14 status/role enums; `UtilityReading` correctly omits `updated_at`/`version` (common_fields: false per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 60 endpoint methods covering all PRD §4 routes
- `api_errors.py` — 39 `ApiErrorId` members + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_invoice_total_invariants`
- `factories.py` — input-only payload factories per entity
- `constants.py` — PRD thresholds (rewash ceiling 2, COG tiers 5000/20000 lb at 3%/7%, RENTAL 2%/piece-day, credit 60%, surcharge tiers 100000/500000 at 50/75/100%, line buffer 10 min)
- `test_users.py` — shared headers for the 5 opaque roles + `make_customer_contact_headers(customer_id)` builder for the entity-backed `CustomerContact`
- `fixtures.py` — composite pipeline helpers (stop-received → batch → finished load → delivered delivery → approved discrepancy → invoice), all built from PRD endpoints, lenient `get_success_data` in setup, `find_cart_by_tag` to defeat same-timestamp list-order ties
- `__init__.py` — barrel export

## Test suite (`test_suite/`, 12 files + conftest.py, 77 tests)
- **Queue A (Difficulty): 36 tests** — all 18 instances × 2, every tag resolves
- **Queue B (Corner): 41 tests** — all 41 translated instances × ≥1

## Instances skipped (1)
- `Corner/validations/mark_lost_blocked_when_chip_tracking_disabled` — the recipe asserts `ERR_CHIP_TRACKING_DISABLED` from `POST /garments/register` for a chip-disabled customer, but the PRD names that error only for mark-lost ("Marking lost requires the owning customer to have `chip_tracking_enabled`…"), and says nothing about registration being blocked — fails PRD coverage. Gap left as a gap.

## Adjudications applied (PRD over index literals)
- **Version base value**: instances `plant_create_returns_201_with_defaults` and `system_fields_ignore_client_input` assert `version == 1`, but PRD §2.4 says only "starts at its initial value" — never 1. Translated with the derivable conjuncts (201, UUID id, timestamps, `account_balance_cents == 0`, `ACTIVE`); the base-1 conjunct dropped as non-uniquely-derivable.
- **wash_machine_half_open_adjacency_allowed**: trigger reordered (start adjacent load B before creating overlapping load C) — the YAML order would leave C STAGED-overlapping and make B's own start fail under the PRD's STAGED-inclusive conflict set. Both pinned asserts preserved.
- **finish_line_buffered_closed_interval_blocks**: the YAML's "allowed" run at 10:11 is wrong under the PRD's both-sides-buffered closed-interval semantics (its buffered start 10:01 intersects A's [08:50,10:10]). Shifted to 10:21 (buffered [10:11,…] clears), voiding each rejected run so lingering QUEUED runs don't block; added the edge-touch case (10:20) as the second test. Pinned asserts (`ERR_LINE_TIME_OVERLAP`, `TALLIED`) unchanged.
- **utility_surcharge_tiered_min_max_mode_a**: inserted a `POST /_clock/set_current_utc` to 2026-06-10 before unload — the June-billing assert (43750) is only derivable if the unload timestamp lands in June, and the default logical clock is 2026-05-01.

## Self-check verdicts
- **Stage 1**: PASS — all helpers compile; package imports cleanly (95 client-visible methods).
- **Stage 2**: PASS — 77/77 tests collected by pytest; 77/77 docstrings carry exactly one resolving `Design:` tag; 110/110 quoted PRD citations grep verbatim against PRD.md; no skip/xfail/skipif markers; no scaffold references in generated code.

## Step 6: Generate implementation — 2026-08-12T04:51:25.710Z

Implementation complete for `task_1231_industrial_laundry_plant`. All verification steps passed.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1231_industrial_laundry_plant/workspace/implementation/`)

| File | Size |
|---|---|
| `start.sh` | 396 B (executable, `exec python3 app.py`, `$PORT` default 10000, `0.0.0.0`, guarded `pip install`) |
| `requirements.txt` | 11 B (flask only) |
| `app.py` | 988 B (entry point, ApiError/404/405/500 envelope handlers) |
| `db.py` | 1,713 B (empty in-memory dicts, id/timestamp/version helpers) |
| `errors.py` | 2,907 B (all 37 scaffold error IDs) |
| `clock.py` | 1,473 B (logical clock, pinned initial `2026-05-01T00:00:00Z`, 3-fraction-digit ISO) |
| `util.py` | 5,429 B (auth headers, role checks, priority-0 body schema, pagination) |
| `response.py` | 1,180 B (`meta`/`response_type`/`data` envelope, list pagination meta) |
| `services.py` | 13,777 B (garment cascades, stop/delivery lifecycle, machine/line overlap guards, COG tiered + RENTAL charges, tiered utility surcharge with estimated/actual variants and true-up) |
| `routes/__init__.py` + 8 modules (`core`, `customers`, `transit`, `sort`, `wash`, `garments`, `delivery`, `billing`) | 339 B – 12,679 B each |

## Route parity
**91 implemented (method, path) pairs vs 91 scaffold endpoints — 0 missing, 0 extra.**

## Boot check
`bash start.sh` booted cleanly on three separate fresh ports; each boot served requests within ~1s and was killed cleanly afterward (per-test-server restart semantics verified). Live curl checks confirmed: envelope shape, logical-clock timestamps, 401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED_ROLE`, 404 `ERR_NOT_FOUND`, and priority-0 ordering (400 `ERR_INVALID_REQUEST` returned before auth when body is invalid).

## End-to-end smoke (fresh boot, full lifecycle) — PASSED
plant → category → customer → par upsert → garment register → route/dispatch/arrive/pickup → cart receive (actual weight recompute 48.0, garment cascade) → sort batch items/lock (reject rate 16.67%, alert raised at ≥8.0) → post (carts SORTED, par −10) → wash load start/FAIL/rewash (formula escalated WF_STANDARD→WF_HEAVY_SOIL, count 1)/PASS/unload (clean_weight 25.0 lb) → finish run tally (loss 1, throughput 9.0/hr)/post → delivery manifest/mark-delivered (shortfall 2, par +8, OCC on `expected_customer_version`, stop→DELIVERED) → dispute/approve (credit = 2×1000×60% = 1200) → invoice generate (COG 1250, no volume discount) → apply-credit (total 50, delivery SETTLED, stop CLOSED) → issue/mark-paid (balance −1150→−1200) → route complete/reconcile → utility reading true-up (delta-only DRAFT with surcharge 33500) → load-out/mark-lost → lost-charge drain (1000) on next generate → billing preview.

## Constraint compliance
- Storage is in-memory dicts only; grep confirms no file/DB/tmp persistence and no seeding (store boots empty every launch).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` were never read; no other task directory was inspected.
- Key semantics implemented per PRD: validation priority order (schema → auth → role → path → refs → state → business → OCC), half-open machine intervals vs buffered closed line intervals (10-min buffer), reject-rate `>=` alert comparison, pinned COG rounding order (per-category gross → discount → sum), rental 2%/piece-day, tiered utility pass-through (50/75/100 at 100k/500k caps) with 4-decimal share, estimated-variant trailing-3-month window with true-up to next DRAFT (or new delta-only DRAFT), 60% discrepancy credit, rewash ceiling 2 with formula ladder, OCC on the two named endpoints, and CustomerContact ownership via `X-User-ID`.

## Step 7: Run tests and iterate — 2026-08-12T05:10:07.280Z

## Summary

**Iterations run:** 2 (sweep 1: 23 distinct failing tests in the union; sweep 2: 77/77 passed in all 8 rounds).

**Tests deleted:** none — every failing assertion traced to a verbatim PRD rule; all failures were fixable as test-artifact or implementation bugs.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `receive_stop_carts` returned the pre-receive cart list, so `ctx["carts"]` showed stale `DECLARED` status; now re-lists after receiving so callers observe the true `RECEIVED` state (fixed `test_cart_receive_in_terminal_state_rejected`, 8/8 rounds).
- `test_helpers/api_client.py` — `ApiClient.__init__` now sets `Connection: close` on the session; the session-scoped keep-alive pool held dead connections across per-test server SIGKILL/reboot cycles, causing the flaky `ConnectionResetError(104)` failures.

**Fixes applied to `test_suite/`** (all re-anchoring the rejection point to what PRD §2.9 item 9 uniquely determines — temporal-integrity guards apply at "wash-load staging, wash-load starting, finish-run queuing, and finish-run tallying"):
- `test_07_resource_scheduling.py::test_adjacent_load_allowed_overlapping_load_rejected` — overlapping load C is now rejected with `ERR_MACHINE_TIME_OVERLAP` at staging (was: stage-then-start, which §2.9 makes unreachable).
- `test_07_resource_scheduling.py::test_buffered_overlap_rejected_and_clear_run_tallied` — run B now expects `ERR_LINE_TIME_OVERLAP` at queuing; removed the unreachable tally/void of B; the clear run D (201 → TALLIED) path unchanged.
- `test_07_resource_scheduling.py::test_buffered_edges_touching_is_a_conflict` — touching-edge run E now expects `ERR_LINE_TIME_OVERLAP` at queuing.
- `test_09_deliveries_and_disputes.py::test_unresolved_carts_block_delivery` — PRD §3.7 gates the manifest act itself on carts resolved ("Once a stop is PICKED_UP and every cart … resolved … the RouteDriver manifests …"); the mark-delivered paragraph names no carts error. Test now expects `ERR_CARTS_PENDING` from `create_delivery` (also matching its own design instance name `error_carts_pending_blocks_delivery_manifest`).

**Fixes applied to `implementation/`:**
- `implementation/db.py` — `new_entity` now mints `str(uuid.uuid4())` (canonical dashed form) instead of `uuid.uuid4().hex`; PRD §2.4's "server-minted UUID" is asserted via the harness's `is_valid_uuid`, which requires the dashed form (fixed 6 tests across all rounds).
- `implementation/start.sh` — dependency check now writes a `.deps_ok` marker on first boot; steady-state reboots skip the duplicate `python3 -c "import flask"` spawn, halving per-boot cost. This eliminated the flaky "API server could not be restarted" failures (15s poll window overruns under 8× parallel load; ~10 per sweep previously, 0 in the final sweep). Bytecode was also precompiled with `compileall`.

**Verification:** final 8-round parallel sweep: all rounds 77/77 passed, zero flakes. Orchestrator re-verified on disk: results.1..8.json all report total=77 passed=77 failed=0 errors=0 skipped=0.

## Step 8: Finalize PRD — 2026-08-12T05:18:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1231_industrial_laundry_plant/workspace/PRD_FINALIZED.md` with exactly three inline revisions, no new sections.

**Line counts / delta:** PRD.md 379 lines, PRD_FINALIZED.md 379 lines — 0% line-count delta; 3 lines revised in place, nothing added or removed structurally.

**Changes (one bullet per edit):**
- §2.4 — revise — pinned the server-minted resource `id` to the canonical hyphenated 8-4-4-4-12 lowercase hexadecimal string form (previously just "a server-minted UUID with no type prefix", which also admitted the undashed `uuid4().hex` form the implementation originally shipped) — `implementation/db.py:46` (`str(uuid.uuid4())` in `new_entity`, the sole mint site for every entity).
- §3.4 (wash-load staging paragraph) — revise — inserted "Staging also enforces the machine's half-open overlap guard of §2.8 against the proposed window, rejecting conflicts with `ERR_MACHINE_TIME_OVERLAP`." — `implementation/routes/wash.py:64-65` (guard fires at staging, not only at start).
- §3.5 (finish-run queuing paragraph) — revise — inserted "Queuing also enforces the line's buffered closed-interval guard of §2.8 against other `QUEUED` or `TALLIED` runs on the same line, rejecting conflicts with `ERR_LINE_TIME_OVERLAP`." — `implementation/routes/wash.py:243-244` (guard fires at queuing, not only at tally).

**Step 7 items judged to need no PRD edit:** the two `test_helpers/` fixes (stale post-receive cart list in `fixtures.py`; `Connection: close` in `api_client.py`) are pure test-harness bugs; `start.sh`'s `.deps_ok` marker is boot infrastructure with no API-visible behavior; the `test_09` carts-pending fix re-anchored to behavior PRD §3.7 already pins verbatim (impl `routes/delivery.py:55-62` matches: stop-status check then cart-resolution check at manifest time); the `test_07` re-anchors were globally determined by §2.9 item 9 but the §3.4/§3.5 operation narratives were locally silent, which is what edits 2 and 3 close.

**Per-edit pre-edit search log:**
1. *UUID edit* — (a) subject: serialization form of server-minted resource `id`. (b) enumerated: `db.py:42-50` (sole mint; confirmed via grep that all 17 creation sites in `routes/*.py` plus the true-up invoice at `services.py:384` go through `new_entity`); `util.py:130-144` (path/reference lookups are format-agnostic dict lookups, so wording describes minting only, not input validation); `response.py:14` (`api_request_id` is a distinct `req_`-prefixed field pinned by §2.2 — wording kept scoped to "persisted resource ... id"); harness regex `^[0-9a-f]{8}-...{12}$` (case-insensitive) at `prd_bench_local_runner/testing/assertions.py:19`. (c) scoped the sentence to persisted-resource ids and to rendering form; no uppercase/lowercase conflict since impl always emits lowercase.
2. *§3.4 staging guard* — (a) subject: machine-overlap guard application points. (b) enumerated: `wash.py:64-65` (staging, no self-exclusion — load not yet created), `wash.py:127-128` (start, `exclude_id=load["id"]`, covers STAGED and REWASH_PENDING starts per line 120), `services.py:145-158` + `services.py:25` (half-open test and active-state set match §2.8 verbatim); no other `machine_conflict` call sites. (c) wording mirrors §2.8/§2.9 and makes no ordering claim vs. the time-range check (both in §2.9 item 9; impl checks time-range first — left undetermined deliberately).
3. *§3.5 queuing guard* — (a) subject: line-overlap guard application points. (b) enumerated: `wash.py:243-244` (queuing), `wash.py:304-305` (tally, `exclude_id=run["id"]` — necessary since the tallied run is itself QUEUED), `services.py:161-178` + `services.py:23,26` (10-minute closed buffer, `{QUEUED, TALLIED}` states — match §2.8 verbatim); no other `line_conflict` call sites. (c) phrasing mirrors the existing tally sentence ("against other `QUEUED` or `TALLIED` runs on the same line") so queuing and tally read identically; additive only.

## Step 9: Complete PRD — 2026-08-12T05:31:01.494Z

All 28 edits applied cleanly. Final verification of counts is done. Here is the summary.

## Summary

**Source:** `PRD_FINALIZED.md` (379 lines, 59,211 chars) → **`/home/ubuntu/github/CodingPRD/tasks/task_1231_industrial_laundry_plant/workspace/PRD_COMPLETED.md`** (382 lines, 61,925 chars; +3 lines, +2,714 chars).

**Counts:** 18 ambiguity-pins, 10 mismatch-revisions (28 inline edits total; no new sections).

### Ambiguity-pins (PRD silent → pinned to impl)

- §2.2 — insert — ambiguity — pins unrouted path → `ERR_NOT_FOUND` (404), unsupported method → `ERR_INVALID_REQUEST` at HTTP 405, unexpected failure → `ERR_INTERNAL` (500) — implementation/app.py:20-30
- §5 — insert — ambiguity — adds `ERR_INTERNAL | 500` catalogue row — implementation/app.py:28-30
- §2.3 — insert — ambiguity — limit/offset out-of-range values are clamped (limit to [1,100], offset to ≥0), non-integer values fall back to defaults; ties on `created_at` broken by creation order; `has_more` ⟺ `offset`+`limit` < `total_count` — implementation/util.py:148-172, implementation/db.py:64-66
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — implementation/db.py:42-50
- §2.5 — insert — ambiguity — clock endpoint returns body field `current_utc`; request datetimes without an offset are interpreted as UTC — implementation/routes/core.py:25-33, implementation/clock.py:27-38
- §3.2 — insert — ambiguity — stops may be added in any route status — implementation/routes/transit.py:133-155
- §3.2 — insert — ambiguity — pickup rejections ordered: stop-state → non-empty payload → tag uniqueness; response returns the updated stop — implementation/routes/transit.py:203-227
- §3.3 — insert — ambiguity — sort batch is stamped with the plant of the stop's route — implementation/routes/sort.py:47-69
- §3.4 — insert — ambiguity — multiple wash loads may be staged for the same batch and category; each computes `clean_weight_lb` independently at unload — implementation/routes/wash.py:42-84, 197-213
- §3.5 — insert — ambiguity — queuing a finish run is not gated on the wash load's state — implementation/routes/wash.py:229-261
- §4 — revise — ambiguity — table cell "for a finished wash load" → "for a wash load" (companion to the §3.5 pin) — implementation/routes/wash.py:229-261
- §3.6 — insert — ambiguity — garment registration does not require `chip_tracking_enabled`; the flag gates only cascades and mark-lost — implementation/routes/garments.py:28-51, services.py:89-91
- §3.7 — insert — ambiguity — manifesting enforces no (stop, category) uniqueness; duplicate category manifests create multiple rows — implementation/routes/delivery.py:46-76
- §3.8 — insert — ambiguity — `billing_period_start`/`end` are `YYYY-MM-DD` dates; invoice month is the `YYYY-MM` of `billing_period_start` — implementation/routes/billing.py:37-69
- §3.8 — insert — ambiguity — COG period containment compares the unload calendar date (start-inclusive, end-exclusive) — implementation/services.py:196-201
- §3.8 — insert — ambiguity — surcharge share is zero when `clean_lbs_processed` is zero (actual variant) — implementation/services.py:296
- §3.8 — insert — ambiguity — true-up delta lands on the customer's earliest-created `DRAFT` invoice; the delta-only invoice's period is the reading's month (1st→1st) — implementation/services.py:369-401
- §3.8 — insert — ambiguity — preview: in-flight loads counted with no period filter; estimated projection applies to the linen component only (surcharge computed as at generation); `override_par_pieces` is a non-negative integer applied to every par row — implementation/routes/billing.py:173-206, services.py:203-212, 238

### Mismatch-revisions (PRD described behavior impl does not exhibit)

- §2.4 — revise — mismatch — marking a delivery delivered bumps customer `version` without changing `account_balance_cents` — implementation/routes/delivery.py:139-140
- §2.9 item 10 — revise — mismatch — stop+`cart_tag` uniqueness raises `ERR_DUPLICATE_CART_TAG` (not `ERR_DUPLICATE`); par-level upsert removed from the uniqueness list — implementation/routes/transit.py:207-211, customers.py:119-150
- §3.1 — revise — mismatch — `par_shortage_alert_pieces` is stored but inert; no par-shortage alert is computed anywhere — implementation/routes/delivery.py:121-131 (no alert logic exists)
- §3.1 — revise — mismatch — category `code` uniqueness per plant is not enforced — implementation/routes/core.py:67-92
- §3.1 — revise — mismatch — balance is a stored running ledger (issue adds, pay subtracts, credit subtracts), not a computed "sum of unpaid totals minus credits" — implementation/routes/billing.py:134, 150, delivery.py:287
- §3.1 — revise — mismatch — par-level upsert never raises `ERR_DUPLICATE`; responds HTTP 200 on both create and update; on-site counter never floored at zero; no par row ⇒ no counter movement — implementation/routes/customers.py:119-150
- §3.4 — revise — mismatch — a healthcare `TESTED_FAIL` sets no alert flag on the load — implementation/routes/wash.py:148-163
- §3.5 — revise — mismatch — no plant-level loss ledger read; `linen_loss_pieces` lives only on the run — implementation/routes/wash.py:318-333
- §3.7 — revise — mismatch — mark-delivered raises no par-shortage alert; par increment only when a par row exists — implementation/routes/delivery.py:121-131
- §3.8 — revise — mismatch — estimated surcharge trailing window is the up-to-three most recent readings strictly before the invoice month (not the three immediately-preceding calendar months); zero-divisor share pinned — implementation/services.py:298-312

Notable non-changes (verified consistent, left untouched): the pickup variance prose in §3.2 is definitional only (impl exposes both weights; no variance field is claimed); validation pipeline order in §2.9 matches impl (body → auth → role → path → refs → state → …); all endpoint/role assignments in §4 match the routes exactly; COG tiered discount, RENTAL 2%/day formula, tiered utility pass-through, rewash ladder, and garment cascade order all matched impl verbatim.
