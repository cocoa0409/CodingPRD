# Worklog — task_0308_brewery_winery_tasting_room

## Step 1: Create task directory — 2026-06-12T02:34:27.000Z

Task directory pre-assigned: `tasks/task_0308_brewery_winery_tasting_room`. Verified it exists with an empty `workspace/` subdirectory. No index auto-computation performed (directory pre-assigned per orchestrator instructions).

## Step 2: Generate scaffold (Expert tier) — 2026-06-12T02:56:15.000Z

## Scaffold generation complete — task_0308_brewery_winery_tasting_room (Expert tier)

**Domain:** brewery-winery-tasting-room | **api_prefix:** `/` (flat topology) | **Archetype:** quota_allocation + compliance_audit | **Layers:** rate/threshold, cascading side-effects, derived-field reconciliation, optimistic concurrency | **Role model:** peer_roles | **Consistency:** immediate.

**Files written (all three):**
- `SCAFFOLD.yaml` (§1.0–§1.7, neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Seed-table counts:**
- **Entities:** 11 — Winery, ProductionBatch, Product, AllocationRelease, Member, Membership, Shipment, TastingOrder, Reservation, DistributionOrder, ComplianceLedgerEntry (immutable event log, common_fields:false). 17 FKs, all with reverse-reachability GETs.
- **State machines:** 10 — ProductionBatch (branching fork to DUMPED + bottling self-loop), Product (OCC), AllocationRelease (OCC quota window), Member (cascade on SUSPEND), Membership (branching + parallel billing dimension), Shipment (branching SCHEDULED→{RELEASED,HELD} with HELD→RELEASED revert), TastingOrder (PAY/REFUND compensation), Reservation (CONFIRMED→NO_SHOW revert), DistributionOrder, Winery (OCC suspend/reinstate). Plus 3 concurrency_rules (OCC on Product/AllocationRelease/Winery versions, all 412).
- **Calculations:** 8 — excise_accrual (dual-variant WINE-tiered vs BEER-per-barrel), loyalty_points_accrual (dual-variant membership-balance vs winery-liability), shipment_pricing (combinatorial mode a), pos_order_total (combinatorial mode b, round-per-line-then-sum pinned), ship_state_limit_check (strict-> threshold), bottling_removal_accounting, distribution_invoice (combinatorial mode c, eval-order pinned), event_deposit.
- **Validations:** 17 (priority-ordered, 8 categories auth→business_fiscal).
- **Endpoints:** 44 (43 business + 1 `/_clock/set_current_utc` test-driving).
- **Errors:** 23.
- **Roles:** 5 — ComplianceOfficer, CellarManager, ClubManager, TastingRoomStaff (all opaque), Member (entity_backed:Member).

**Difficulty design (§1.8):** 19 instances across all 9 §0.5 rules (each ≥2; combinatorial_formula has 3 to cover modes a/b/c distinctly). All asserts pinned to code-computed literals.

**Corner design (§1.9):** 37 instances (32 active + 5 `excluded_because` stubs) spanning all 9 claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).

**Lint:** `python3 scaffold_lint.py <task-dir>` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (44 endpoints, 11 entities, 19+32 instances, 407 calls scanned, exit 0). Name uniqueness, excluded_because resolution, error-reference coverage, enum closure, and the no-forbidden-concurrency-vocab / no-id-in-decisions rules all verified clean.

## Step 3: Copy INSTRUCTION.md — 2026-06-12T02:56:38.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-12T03:03:00.000Z

PRD generated at `workspace/PRD.md`.

**Document stats:** 5 top-level sections, 22 subsections (§1 Introduction; §2 with 10 subsections §2.1–§2.10; §3 with 12 workflow subsections §3.1–§3.12; §4 Endpoint Definitions; §5 Error Code Catalogue), 294 lines.

**Coverage confirmation — every scaffold element is in prose:**
- **Entities (11):** Winery, ProductionBatch, Product, AllocationRelease, Member, Membership, Shipment, TastingOrder, Reservation, DistributionOrder, ComplianceLedgerEntry — all narrated with computed/derived fields. ComplianceLedgerEntry's `common_fields: false` (only `id`+`created_at`) stated explicitly.
- **State machines (10):** all transitions (branching forks FERMENTING→{AGING,DUMPED}, SCHEDULED→{RELEASED,HELD}, bottling self-loop, CONFIRMED→NO_SHOW revert, both Membership CANCEL branches) framed by state-pair; preconditions→errors and side-effects/cascades stated (depth-3 bottling cascade; member-suspend→membership-pause→shipment-cancel→release-free chain; refund/cancel compensations).
- **Calculations (8):** excise_accrual (WINE tiered 107/157 at 14.0 ABV; BEER 31-gal barrels @1800; CIDER flat 23), loyalty_points_accrual (mult 1/2/3, floor-earn, ceil-redeem), shipment_pricing (tier + 12-bottle kicker 0.05, cap 0.18 last), pos_order_total (round-per-line-then-sum pinned), ship_state_limit_check (9L cases, strict >, CA24/NY36/TX9/PA0/default24, 365-day window), bottling_removal_accounting, distribution_invoice (0.50 wholesale, freight tier on base, 50000/1500/2500), event_deposit (1500/guest). Round-half-up + pinned rounding orders stated.
- **Validations (17):** full priority order in §2.9; each check→error_id; applies_to scopes enumerated.
- **Concurrency rules (3):** all OCC rejections expressed (write_endpoint via state-transition framing, expected_<parent>_version field, mismatch rejection, exact error_id + HTTP 412).
- **Endpoints (43):** §4 4-column table; all params reachable in backticks.
- **Errors (22):** §5 2-column table; every error ID also triggered in §2/§3 narrative.

**Hard Contracts:** Field coverage PASS (84/84), Rule coverage PASS (17 validations, 3 OCC, 10 SMs, 8 calcs, sibling-branch symmetry clean), Path purity PASS (536 backtick tokens scanned, 0 path/method leaks in §3). Withheld SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were not opened.

## Step 5: Generate unit tests — 2026-06-12T03:20:53.000Z

Test infrastructure generation complete for task_0308_brewery_winery_tasting_room.

**Helper files generated (`test_helpers/`, 9 files):** `__init__.py` (barrel export), `types.py` (entity TypedDicts + status/role enums; ComplianceLedgerEntry correctly carries only id+created_at, no updated_at/version), `api_client.py` (one method per endpoint), `api_errors.py` (22 error IDs + HTTP-status map), `assertions.py` (per-entity asserts + reconciliation invariants), `factories.py` (per-entity payload factories, optional fields omitted per PRD), `constants.py` (excise/loyalty/pricing/state-limit/freight/deposit constants), `test_users.py` (4 opaque staff role headers + entity-backed `make_member_headers`), `fixtures.py` (8 tiers of composite setup).

**Test files generated (`test_suite/`, 8 files + conftest.py): 69 test functions.**

**Queue A — Difficulty (19 instances, ALL translated, 2 tests each = 38 tests):** every one of the 9 rules' 19 instances covered by exactly 2 tests. 0 skipped.

**Queue B — Corner (32 non-stub instances): 31 translated (1 test each), 1 skipped.**
- Skipped: `endpoints/list_releases_filtered_by_product` — no verbatim PRD prose defines a `product_id` query-filter on `GET /releases` (PRD §2.3 names only `limit`/`offset`); §4 table row is endpoint-titular only, failing both Coverage and unique-derivability. Companion `list_shipments_pagination_envelope` WAS translated (empty-envelope shape is verbatim PRD-covered).
- All 5 `excluded_because:` stubs verified to cross-reference real difficulty instances.

**Validation:** All 69 tests passed against the reference implementation (single-server run + via `prd-bench-local-run` with `--skip-lifecycle`, JUnit XML, 69 passed). Caught & fixed two test-side defects during validation: (1) GOLD-tier loyalty expectation that omitted the +0.05 volume kicker at 12 bottles (PRD-correct = 1020 not 1080); (2) stale `expected_winery_version` in suspend-blocks-bottling test (batch creation advances winery version; now re-read before SUSPEND). Every docstring carries a verbatim PRD citation + exactly one `Design:` tag; no untagged/dual-tagged tests, no skip/xfail.
- NOTE: the runner's per-test-server-isolation mode failed to boot in the unit-test-gen sandbox (dnsboot-wrapped lifecycle, exit -15) — flagged as an environment quirk; Step 7 runs the authoritative per-test-server sweep.

## Step 6: Generate implementation — 2026-06-12T03:20:53.000Z

Complete Python + Flask implementation generated at `workspace/implementation/`.

**Source files generated (29 total):** `start.sh`, `requirements.txt` (Flask 3.0.3); Core: `app.py`, `db.py` (in-memory store), `errors.py` (22-error catalogue), `response.py` (meta/response_type/data envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `util.py`, `clock.py`, `constants.py`, `serialize.py`, `pagination.py`, `validate.py`; Business: `calculations.py`, `domain.py`, `ledger_service.py`, `club_service.py`; 12 route modules under `routes/`.

**Endpoint count:** 44 routes implemented, covering every row of the PRD §4 endpoint table (11 entity collections + ledger reads + `_clock` test-driving route).

**Verification:** 62 manual assertions passed across four test scripts — depth-3 bottling cascade with exact round-half-up excise (WINE tier-1/tier-2 by ABV, BEER per-barrel, CIDER flat), product/release/winery OCC version guards, capped volume-kicker shipment discount (0.20→0.18), floor×tier loyalty accrual, per-line-rounded POS totals, freight-tier on post-discount wholesale base, PA state-limit (0 cases), hold-reason priority ordering, member-suspend cascade, loyalty-forfeit + winery-liability reconciliation, table double-booking (half-open intervals), Member self-service ownership, FK winery-scoping, pagination meta.

**Constraints confirmed:** Storage in-memory only (plain dicts in `db.py`; nothing seeded/preloaded/hardcoded; fresh boot returns total_count 0). `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`, guards `pip install` behind a Flask import check so per-test reboots don't re-install.

## Step 7: Run tests and iterate to PASS — 2026-06-12T03:31:21.000Z

All tests pass cleanly across the stability sweep.

**Iterations run:** 3 sweeps (1 diagnostic baseline + 2 confirmatory). Final state: two consecutive clean 8-round parallel sweeps, **69/69 passing in all 16 rounds**.

**Diagnosis:** The baseline sweep showed a single consistent failure across all 8 rounds: `test_ledger_entry_immutable_no_version_field` (in `test_05_entities_crud.py`) failed on **setup** — not on assertion — with `"API server ... could not be restarted"`. The runner logs showed all 8 rounds attempting the per-test server restart at the exact same instant (11:23:46.22x) and the boot exceeding the runner's 15s restart-poll window. This is the timing-sensitive 8x-concurrent-boot contention the harness is designed to surface, not an implementation logic bug or an unfair test. The test itself is PRD-faithful (cites §2.4 ledger immutability and §3.3 dual-ledger-entry verbatim), so it was correctly kept.

**Root cause:** Under 8 simultaneous Flask boots, two stdlib calls in Werkzeug's dev server stall a fresh boot: (1) `HTTPServer.server_bind()` → `socket.getfqdn("0.0.0.0")` blocks on a no-answer reverse-DNS lookup on macOS; (2) `werkzeug.serving.log_startup()` → `get_interface_ip()` opens a UDP socket to an external address just to print a banner. The runner's injected `sitecustomize` only patches case (1), and only when its PYTHONPATH injection loads.

**Tests deleted:** None. The sole failing test was PRD-covered and uniquely-derivable; the failure was environmental boot contention, not an assertion mismatch.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:**
- `workspace/implementation/app.py` (module top-level, before app construction): made the server self-sufficient against boot stalls regardless of the runner's injection. Added a `socket.getfqdn` fast-path returning `"localhost"` for unspecified addresses (`0.0.0.0`/`::`), and monkeypatched `werkzeug.serving.BaseWSGIServer.log_startup` to a no-op to eliminate the banner's `get_interface_ip` UDP probe. Both calls are cosmetic/logging-only and never affect request handling, so responses are byte-identical; the boot is now fast and deterministic under 8x contention.

No entity data is seeded or persisted (storage remains in-memory dicts; no disk/file/sentinel state added), so `start.sh` re-invocation still wipes every byte of state. `start.sh` was left with its existing guarded-install idiom unchanged.

## Step 8: Finalize PRD — 2026-06-12T03:33:01.000Z

Step 8 run (NOT skipped: Step 7 had 1 implementation/ fix, so skip condition unmet). Outcome: **zero edits**.

**PRD.md vs PRD_FINALIZED.md:** 294 lines vs 294 lines — 0% delta (verbatim identical copy; `diff` confirms identical).

**Change log:** Zero edits — the single Step 7 fix was environmental (app.py boot-mechanics shims) and reveals no PRD silence or PRD/impl behavioral mismatch.

**Pre-edit search (applied to the lone Step 7 diff item to decide it warranted no edit):**
- (a) Subject: app.py module-top-level boot shims — `socket.getfqdn` fast-path returning "localhost" for unspecified addresses; monkeypatch of `werkzeug.serving.BaseWSGIServer.log_startup` to a no-op.
- (b) Impl paths enumerated: read app.py in full; both shims execute at import time before `create_app()` and before any route handles a request; no route/validator/calculation/serializer/response path references getfqdn/log_startup; all business logic lives in routes/, calculations.py, validate.py, domain.py; storage remains in-memory dicts.
- (c) Wording adjustment: none — no PRD prose describes server hostname resolution, FQDN/reverse-DNS, dev-server banners, or boot timing; shims produce byte-identical HTTP responses, invisible to every API client. Correct outcome is verbatim copy with zero edits.

## Step 9: Complete PRD — 2026-06-12T03:41:23.000Z

Full PRD-vs-implementation completeness scan. `PRD_COMPLETED.md` produced.

**Source vs Completed:** Source `PRD_FINALIZED.md` (identical to PRD.md) — 294 lines, 54,456 chars. Output `PRD_COMPLETED.md` — 294 lines, 59,499 chars. Char-delta **+5,043** (all edits in-paragraph; line count unchanged; no new sections).

**Counts:** ambiguity-pins: 9 · mismatch-revisions: 5 (14 edits total).

**Per-change bullets:**
- §3.1 Founding the Premises — revise — mismatch — `ttb_permit_number` "unique" not server-enforced (no uniqueness error in catalogue); pinned as caller-supplied — `routes/wineries.py:30-41`, `errors.py:12-34`
- §3.2 Batch Lifecycle — revise — mismatch — `lot_code` "unique within winery" not server-enforced — `routes/batches.py:42-58`
- §3.3 Bottling cascade — insert — ambiguity — bottling-run returns updated batch resource at HTTP 201; pinned ledger `volume_gallons`/`excise_cents` field values per entry — `routes/batches.py:205,200-203`
- §3.3 Bottling permission — revise — mismatch — pinned error codes/order: batch-not-BOTTLING→`ERR_INVALID_STATE`; product unresolved/wrong-batch/`DISCONTINUED`→`ERR_FK_NOT_FOUND`; eval order FK→state→suspension→sourcing→bulk — `routes/batches.py:160-179`
- §3.4 Products — revise — mismatch — `sku` "unique" not server-enforced — `routes/products.py:39-58`
- §3.4 Product lifecycle — insert — ambiguity — ACTIVATE source-batch-not-BOTTLING/CLOSED and DISCONTINUE open-release conditions both raise `ERR_INVALID_STATE`, evaluated before the version check — `routes/products.py:100-123`
- §3.5 Release open — insert — ambiguity — product-not-ACTIVE→`ERR_INVALID_STATE`; pinned eval order (state→release-ver→product-ver→inventory) — `routes/releases.py:106-118`
- §3.6 Members — revise — mismatch — `email` "unique" not server-enforced — `routes/members.py:35-50`
- §3.6 Membership cancel — insert — ambiguity — cancel advances membership `version` by two (status change + loyalty forfeiture = two mutations) — `routes/memberships.py:123-134`
- §3.7 Shipment scheduling — revise — mismatch — release-OPEN check first (`ERR_RELEASE_NOT_OPEN`), then §2.9 order cap→window→inventory; pinned cap-counting status set (SCHEDULED/HELD/RELEASED/DELIVERED) — `routes/shipments.py:72-91`
- §3.7 Shipment release/hold — insert — ambiguity — RELEASE permitted from SCHEDULED or HELD; explicit HOLD action (only from SCHEDULED, requires a failing gate else `ERR_INVALID_STATE`) — `routes/shipments.py:272-319`
- §3.7 Standalone compliance errors — revise — mismatch — release/hold paths always divert to HELD (never hard-reject); `ERR_STATE_SHIPPING_LIMIT` and `ERR_BILLING_PAST_DUE` never raised by any operation — `routes/shipments.py:280-299`, `errors.py:24,29`
- §3.9 Tasting order entity — insert — ambiguity — empty `line_items`→`ERR_INVALID_REQUEST`; line `product_id` FK-scoped (`ERR_FK_NOT_FOUND`); stored `unit_price_cents` is resolved (supplied else product list price) — `routes/tasting_orders.py:38-68`
- §3.9 Tasting discount/loyalty — insert — ambiguity — attached member's tier/loyalty resolves via member's earliest-created membership; no membership ⇒ zero discount and `redeem_points>0`→`ERR_INSUFFICIENT_POINTS`; pinned §2.9 pay-gate order (age→inventory→points) — `routes/tasting_orders.py:24-35,189-219`

Tests used only as auxiliary cross-reference; implementation was the sole alignment authority.

---

## PIPELINE COMPLETE — 2026-06-12T03:41:23.000Z

All 9 steps executed end-to-end. Final state: **69/69 tests passing across all 16 rounds (two clean 8-round per-test-server sweeps)**. Deliverables present in `tasks/task_0308_brewery_winery_tasting_room/`: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
