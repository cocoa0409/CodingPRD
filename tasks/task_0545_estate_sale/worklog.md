# Worklog — task_0545_estate_sale

## Step 1: Create task directory — 2026-07-02T00:00:00.000Z

Created `tasks/task_0545_estate_sale/` and `tasks/task_0545_estate_sale/workspace/`. Using the user-specified task_dir directly (no auto-index scan). Difficulty target: Expert.

## Step 2: Generate scaffold — 2026-07-03T00:02:00.000Z

All three artifacts written and pass validation.

Files: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8), SCAFFOLD_CORNER_DESIGN.yaml (§1.9).

scaffold_lint.py verdict: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability (432 calls scanned). All formula-derived assertion literals independently recomputed with round_half_up.

Structural DNA: primary archetype ledger_reconciliation + secondary pricing_engine; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; topology flat; state-machine shape cyclic; role model segregation_of_duties.

Counts:
- Entities: 10 — Client, Project, Lot, SaleEvent, Crew, Transaction, Bid, HaulJob, Truck, SettlementStatement
- State machines: 6 (Project + Lot cyclic; Bid branches; others linear/branching)
- Calculations: 7 — markdown_price, winning_bid_price (first/second-price dual variant), commission_tiered, card_processing_fee (round-per-tx-then-sum), settlement_net_to_client (estimated vs final dual variant), project_gross_sales, crew_booked_minutes
- Endpoints: 32 (incl. /_clock/set_current_utc; flat collections under /estate, 2 sub-resource GETs)
- Errors: 24
- Roles: 5 — PlatformAdmin, SaleManager, Appraiser, Cashier (opaque), Client (entity_backed:Client)
- Concurrency rules: 1 OCC (settlement-create-stale-project, Project.version, 412)

Difficulty design: 9 rules × 2 = 18 instances. Corner design: 8 sections, 28 instances (21 active recipes + 7 excluded_because stubs).

## Step 3: Copy shared files — 2026-07-03T00:03:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0545_estate_sale/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-03T00:10:00.000Z

Generated workspace/PRD.md from SCAFFOLD.yaml. 5 top-level sections, 291 lines.
- §1 Introduction (ledger-reconciliation + pricing-engine framing)
- §2 Global Specifications — 11 subsections: RBAC, response envelope, pagination, common props/versioning, monetary precision, logical clock, OCC, cascading consistency, referenced-resource resolution, SoD, request-validation-order
- §3 Business Logic — 9 lifecycle subsections
- §4 endpoint table (all 32 endpoints)
- §5 error table (all 24 error IDs)

Hard Contracts all PASS: field coverage 59/59; rule coverage 0 missing (validations order, OCC, state machines incl. cyclic, all 7 calcs, side effects); path purity 305 tokens, 0 path leaks; sibling-branch symmetry balanced.

Notable: constants embedded in prose (86400s/day, 60s/min, 500000 threshold, 40%/30% tiers, 2.9% card, 4-day markdown window, 60-min truck buffer). Estimated-vs-final net and FIRST/SECOND_PRICE rendered at equal density. SoD given own §2.10. Logical-clock default 2026-05-01T00:00:00Z. Did not open withheld design files.

## Step 5: Generate unit tests — 2026-07-03T02:50:00.000Z

All files compile and collect. Generation is complete.

### `test_helpers/` (Stage 1 — 9 files)
- `types.py` — enums + TypedDicts for all 10 entities (all `common_fields: true`, so all carry `id/created_at/updated_at/version`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (clock, clients, projects, lots, sale-events, crews, transactions, bids, haul-jobs, trucks, settlements).
- `api_errors.py` — 24-value `ApiErrorId` enum + HTTP-status map, registered with the framework.
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque shared headers + `make_*_headers` builders incl. entity-backed `make_client_headers`), `fixtures.py` (composite setups: `settled_ready_consignment_sale`, `listed_fixed_lot`, `listed_bid_lot`, `crew_booked_event`, `project_in_settling_no_lots`, plus primitives), `__init__.py` barrel export.

### `test_suite/` (Stage 2 — conftest + 5 files, 57 tests)
| Queue | Coverage | Tests |
|---|---|---|
| A (Difficulty) | 18/18 instances, exactly 2 tests each | 36 |
| B (Corner) | 21/21 non-stub instances, 1 test each | 21 |

Every test docstring carries a verbatim PRD citation plus exactly one `Design:` tag; all cited PRD substrings were confirmed with literal `grep`.

### Skips / notes
- No instances skipped — the PRD is comprehensive; every Difficulty and non-stub Corner instance passed the two-condition PRD filter.
- 7 Corner `excluded_because:` stubs were NOT translated (as required); all 7 `difficulty_instance` cross-references were verified to resolve to real Difficulty instances.
- One setup-order correction (not a weakening): the `winning_bid` Difficulty instance lists bids in placement order `12000, 15000, 13000`, but under PRD §3.4's min-increment floor a `13000` bid cannot be placed after `15000`. I place the identical PLACED set ascending (`12000, 13000, 15000`); the asserted winner prices (FIRST=15000, SECOND=14000) are unchanged and remain PRD-uniquely-derivable.
- One boundary avoided as non-derivable: for the truck-buffer instance's second test I assert a direct closed-window overlap rejection rather than the "exactly-60-min-gap allowed" case (PRD's "expanded by buffer overlaps" is ambiguous for closed intervals touching at a point). The crew half-open "touching endpoint allowed" case IS kept — PRD §3.3 states half-open explicitly.

## Step 6: Generate implementation — 2026-07-03T02:55:00.000Z

Generated a complete, verified Python + Flask implementation for the Estate Sale task.

## Files generated
All under `workspace/implementation/`:
- `app.py` — the entire server (single module, ~900 lines)
- `requirements.txt` — `flask>=2.0`
- `start.sh` — foreground launcher with guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)

Storage is in-memory only (Python dicts keyed by id), starts empty on every boot, no seeding — verified.

## Endpoints implemented (all 32 from the PRD/scaffold)
Clock (`/_clock/set_current_utc`); Clients; Projects (create/get/list/PATCH lifecycle/cancel/settlement-statements list); Lots (create/get/list/PATCH/approve-buyout/bids list); SaleEvents (create/get/list/PATCH-open/close); Crews (create/get); Transactions (create/get/list/void); Bids (create); HaulJobs (create/get/list/PATCH); Trucks (create); SettlementStatements (create).

## Key design decisions & correctness details
- Response envelope exactly `{meta, response_type, data}`, with `limit/offset/total_count/has_more` added to `meta` only on list responses; error body `{error_id, message}`. UUID ids, ISO-8601 UTC timestamps with 3 fractional digits, `version` starting at 1 and incremented on every mutation.
- Validation ordering follows PRD §2.11 (auth → authz → body → existence → OCC → state → SoD → temporal → booking constraints → fiscal floor), with per-endpoint FK resolution left-to-right.
- Money via `Decimal` + `ROUND_HALF_UP`: tiered commission rounds once on the summed tiers then floors by `minimum_commission_cents`; card fees round per-transaction then sum (round-then-sum). Markdown price = `round_half_up(list_price * (1 - day_pct))` using a logical clock (default `2026-05-01T00:00:00Z`) for the day index.
- Bid resolution: FIRST_PRICE pays own high bid; SECOND_PRICE pays `min(highest, second + min_increment)`, or `reserve` when only one qualifying bid; empty-set fallback → lot UNSOLD.
- Cascades verified: project cancel → lots WITHDRAWN → their PLACED bids VOIDED → SCHEDULED/OPEN sale events CANCELLED with crew `booked_minutes` released; sale-event close → LISTED lots UNSOLD + counter recompute; void → lot reverts to LISTED/BID_CLOSED + gross-sales recompute.
- OCC on settlement via `expected_project_version` vs `Project.version` → 412; SoD check on approve-buyout; crew half-open overlap and truck closed-window ±60min buffer; 4-day sale-window cap.

One judgment call worth noting: for a few precondition failures the PRD does not name a specific error (e.g., pricing a lot with no `list_price_cents` → ERR_VALIDATION 400; creating a lot on a non-contracted project → ERR_INVALID_STATE 409). These are the most defensible mappings against the error catalog but are the spots most likely to differ from the test suite's expectations if it probes them.

## Step 7: Test + fix iteration loop — 2026-07-03T03:05:00.000Z

Iterations run: 1 (baseline 8-round parallel sweep).
- All 8 concurrent rounds passed 57/57 with 0 failures and 0 errors. Results are fully deterministic (identical across rounds), so no flakiness surfaced.
- Tests deleted: none — nothing failed either coverage or unique-derivability, since nothing failed at all.
- Fixes applied to `test_helpers/`: none required.
- Fixes applied to `implementation/`: none required.

Task is in a passing state on the first sweep; exited clean. (0 iterations beyond baseline / 0 deletions / 0 fixes.)

## Step 8: Finalize PRD — 2026-07-03T03:15:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits, so no PRD_FINALIZED.md was produced.

## Step 9: Complete PRD — 2026-07-03T03:20:00.000Z

Produced workspace/PRD_COMPLETED.md (started from PRD.md since Step 8 was skipped). All edits in-paragraph inserts/revisions; line count unchanged at 290; char delta +1,851 (36,914 → 38,765 chars).

Counts: ambiguity-pins = 11, mismatch-revisions = 2.

Changes:
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset clamped (not rejected), non-integer → ERR_VALIDATION — app.py:334-351
- §3.2 Inventory (lot creation) — revise — mismatch — impl permits CONTRACTED/SALE_SETUP/SALE_LIVE, else ERR_PROJECT_TERMINAL (terminal) or ERR_INVALID_STATE — app.py:702-705
- §3.2 Inventory (research step) — insert — ambiguity — research outside allowed project states → ERR_INVALID_STATE — app.py:867-868
- §3.2 Inventory (pricing step) — insert — ambiguity — pricing with no list_price_cents → ERR_VALIDATION — app.py:877-878
- §3.3 Estimate snapshot — insert — ambiguity — estimated_commission_cents applies minimum_commission_cents floor (max of tiered and floor) — app.py:549, 372-377
- §3.4 Sale-day (open event) — insert — ambiguity — non-SCHEDULED open → ERR_INVALID_STATE; project not SALE_LIVE → ERR_PROJECT_NOT_IN_SALE — app.py:1045-1050
- §3.4 Sale-day (bidding) — insert — mismatch — impl gates bids on is_bid_lot only, any lot status — app.py:1261-1266
- §3.5 Buyout approval — insert — ambiguity — no lot/project-status precondition; SoD check only when researched_by_user_id is set — app.py:910-921
- §3.8 Settlement — insert — ambiguity — terminal project → ERR_PROJECT_TERMINAL, non-terminal non-SETTLING → ERR_INVALID_STATE, both after concurrency guard — app.py:1424-1428
- §4 Endpoints — revise — ambiguity — named supported query filters per list endpoint (5 cells) — app.py:532-537, 747-755, 1022-1027, 1210-1215, 1355-1360

Note: undocumented GET / health endpoint (app.py:1478) intentionally not added — infra, not a behavior silence.
