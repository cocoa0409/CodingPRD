# Worklog — task_1299_vault_cash_federal_reserve_currency

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

Task directory `tasks/task_1299_vault_cash_federal_reserve_currency/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per orchestration instructions. Difficulty target: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-12T20:22:00.000Z

All three scaffold artifacts are generated and pass `scaffold_lint.py` with a clean verdict (342 calls checked across both design files, zero violations; all 15 FKs reverse-reachable).

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1299_vault_cash_federal_reserve_currency/SCAFFOLD.yaml` (§1.0–§1.7 only — no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1299_vault_cash_federal_reserve_currency/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design:` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_1299_vault_cash_federal_reserve_currency/SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design:` key)

## Counts
- **Entities: 13** — VaultSite, StaffMember, Carrier, AtmMachine, SeasonalWindow, FedOrder, DenominationLine, CashShipment, FitnessBatch, CounterfeitCase, CashLedgerEntry, Reconciliation, AtmForecast (flat topology, cross-aggregate FKs; two immutable `common_fields: false` entities)
- **State machines: 7** — FedOrder (cyclic recall + DISPUTED self-loop), CashShipment (EXCEPTION branch/revert), AtmMachine (parallel dimensions: service_status × cash_posture), FitnessBatch (SORTED→OPEN recount cycle), CounterfeitCase (branch with RELEASED revert), Reconciliation (fork-join with auto-fork + system re-derivation flips), AtmForecast (supersede edge)
- **Calculations: 8** — incl. dual variants on two domains (ATM TRAILING vs SEASONAL; recon provisional snapshot vs final with late entries), combinatorial modes (a) residual min/max with posture branch, (b) per-line-then-sum Fed fee rounding (63+63=126 vs 125), (c) insurance headroom with pinned candidate-exclusion evaluation order
- **Endpoints: 64** (incl. `POST /vault-cash/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default; 3 OCC write endpoints)
- **Errors: 47** (12 not-found, 7 invalid-state, 3 OCC 412s, SoD/scope/ownership 403s, temporal/fiscal/constraint splits)
- **Validations: 25** priority-ordered rows across auth → existence → state → cross-entity guards → SoD → insurance-safety → temporal → constraint → fiscal
- **§1.8 instances: 19** — all 9 rules at ≥2 (combinatorial_formula has 3 to cover modes a, b, c)
- **§1.9 instances: 45** (42 active + 3 `excluded_because` stubs), spanning all eight non-error taxonomy sections + consistency model; includes all three OCC stale-version tests (412)

## Design decisions worth noting
- **Archetype**: Ledger reconciliation (primary) × compliance/audit (secondary), with flat entity topology and `segregation_of_duties` role model (counterfeit reporter ≠ seizer; recon locker ≠ counter) plus fine-grained ownership scoping (site-scoped staff via `entity_backed:StaffMember`, carrier-scoped dispatcher via `entity_backed:Carrier`).
- **Accounting coherence**: added `FedOrder.settled_basis_cents` so Fed advice adjustments are basis-relative deltas — the dispute→corrective-advice cycle nets to zero drift (corner instance `fed_advice_dispute_cycle_adjusts_basis` proves it); exception-accept verify books counted (not declared) value to avoid double-counting losses.
- **Boundary discipline**: vault posture uses integer cross-multiplication (no float rounding), so the 90% ELEVATED edge is exact (8,999,999 NORMAL vs 9,000,000 ELEVATED); shrink tolerance 500 inclusive (500 settles, 501 rejected); strap ceiling leaves exact multiples unchanged.
- **Clock determinism**: all temporal rules (order cutoff `(business_date−1d)T18:00Z`, counterfeit report deadlines pressuring posture, backdated ledger entries driving the recon dual-variant split) run on the declared logical clock.
- All formula-derived assert literals were executed and verified numerically before being pinned into the design files; placeholder closure and cross-file name uniqueness (64 names) verified programmatically in addition to the clean lint.

## Step 3: Copy Shared Files — 2026-08-12T20:23:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1299_vault_cash_federal_reserve_currency/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T20:35:00.000Z

All three hard contracts pass. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_1299_vault_cash_federal_reserve_currency/workspace/PRD.md`.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1299_vault_cash_federal_reserve_currency/workspace/PRD.md`
**Line count:** 319 lines

**Section list:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC (all 6 roles with identity-mode prose), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock & Monetary Units, 2.5 Common Resource Properties (incl. `common_fields: false` carve-out for `DenominationLine`/`CashLedgerEntry`), 2.6 Precision & Rounding, 2.7 OCC (all 3 rules), 2.8 Validation Order & Nested Resources, 2.9 Vault Posture thresholds, 2.10 Ledger & Cascading Recompute
- §3 Business Logic & Workflows — 9 subsections organized by business process (site/staff/carrier setup; Fed ordering; insurance headroom; shipments; fitness sorting; counterfeit; ATM forecasting/loading/settlement; reconciliation; manual ledger adjustments)
- §4 Endpoint Definitions — 65 endpoints, 4-column table
- §5 Error Code Catalogue — 47 errors, 2-column table

**Coverage-audit notes:**
- Contract 1 (Field-Name Coverage): PASS — 110/110 required identifiers in backticks (entities, endpoint inputs, path params, common fields, pagination fields). Two repair passes were needed: pass 1 added the 12 path-parameter names (`siteId`, `staffId`, `carrierId`, `atmId`, `windowId`, `orderId`, `shipmentId`, `batchId`, `caseId`, `entryId`, `reconId`, `forecastId`) in a new §2.5 paragraph; pass 2 added `line_cents`, `fee_cents` (§3.2) and `projected_base_cents`, `projected_final_cents` (§3.7).
- Contract 2 (Rule Coverage): PASS — all 41 state-transition pairs named with from/to states; all 32 distinct validation error IDs appear in §2/§3 prose near their triggers (5 invalid-state IDs were repaired into their workflow narratives); all 3 OCC rules express write endpoint + `expected_<parent>_version` field + error ID + HTTP 412; all 47 error IDs present overall; calculation formulas (per-line fee rounding with the 63+63=126 counter-example, weighted forecast with seasonal multiplier, residual-target min/max nesting, posture cross-multiplication with the 90.000% boundary proof, provisional-vs-final reconciliation split, fitness conservation invariant with the 500/501 shrink boundary) are rendered as precise prose with constants embedded in context; validation priority ordering is stated explicitly in §2.8.
- Contract 3 (§3 Path Purity): PASS — 382 backticked tokens in §3, zero path tokens, zero bare HTTP methods, zero method+path combos.
- The forbidden files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-12T20:56:00.000Z

All validation passes. Generation is complete.

## Summary

**Generated 82 tests** across 7 test files plus full `test_helpers/` infrastructure for `task_1299_vault_cash_federal_reserve_currency`.

### test_helpers/ (Stage 1)
- `types.py` — 6 role enum + 12 status enums + 13 entity TypedDicts (DenominationLine/CashLedgerEntry correctly omit `updated_at`/`version` per PRD §2.5)
- `api_client.py` — 47 endpoint methods covering every row in PRD §4
- `api_errors.py` — 47 error IDs with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + site balance-sum and fitness-conservation invariant checkers
- `factories.py`, `constants.py` (fee 1/160, strap 200000, tolerance 500/1000, 45-min turnaround, etc.)
- `test_users.py` — shared admin constant + per-instance `make_*_headers` builders for all 5 entity-backed roles
- `fixtures.py` — composite chains: staffed sites, DRAFT→SUBMITTED→ACKNOWLEDGED orders, order-linked/inter-site shipments through IN_TRANSIT/RECEIVED (both directions), sorted/seized/recon/forecast lifecycle shortcuts

### test_suite/ (Stage 2) — per-file breakdown
| File | Tests | Covers |
|---|---|---|
| `test_01_fed_order_calculations.py` | 6 | per-line fee rounding (63+63=126), computed line fields, line-add OCC |
| `test_02_atm_forecasts.py` | 8 | TRAILING vs SEASONAL, residual-target 3-branch min/max, exact strap multiple, supersede, publish OCC, load/settle cycle |
| `test_03_fed_order_lifecycle.py` | 10 | initial state, recall cycle, cutoff, FROZEN submit block, deposit sufficiency, advice dispute basis-relative deltas, immediate consistency, missing/invalid direction, bundle multiples, 404 |
| `test_04_shipments.py` | 10 | ACKNOWLEDGED load gate, exception→accept variance, turnaround 45-min boundary, dock capacity, insurance-beats-liability, cancel compensation (SCHEDULED + LOADED), carrier ownership |
| `test_05_fitness_and_counterfeit.py` | 10 | conservation across recount, shrink 501, invalid/double settle, unfit escrow, seize cascade, state-beats-SoD, SoD report, terminal lockdown, compliance lifecycle |
| `test_06_reconciliation_and_ledger.py` | 8 | provisional vs final divergence, business-date input filtering, auto-fork, verify→recon flip cascade, duplicate recon, lock SoD, cascaded site version |
| `test_07_posture_security_envelope.py` | 12 | 90.000% posture boundary, headroom evaluation order, missing-auth-beats-404, RBAC/scope violations, seasonal window overlap, site-patch OCC, envelope shapes, pagination, ATM parallel axes, creation defaults, system-field ignoring, unknown-site FK |

### Skipped instances
None. All 19 difficulty instances and all 40 non-stub corner instances passed the PRD-first two-condition filter — the PRD uniquely derives every asserted outcome (including §2.8's fixed validation order, which legitimately covers the two priority-pair instances). The 3 `excluded_because` corner stubs (`forecast_weight_constants_applied`, `fee_per_line_rounding_precision`, `carrier_dispatcher_depart_own_shipment`) were not translated; their difficulty-design cross-references all resolve and own the assertions.

### Validation results
- **Stage 1**: all helper modules byte-compile and import cleanly (70 client attrs, 47 errors registered); append-only TypedDicts omit `updated_at`/`version`.
- **Stage 2**: 82/82 tests collected by pytest with zero import errors; every difficulty instance has ≥2 tests and every non-stub corner instance has ≥1; no untagged or dual-tagged tests; every `Design:` tag resolves to a real instance name in the source YAML; all 129 PRD docstring citations survive whitespace-normalized verbatim grep against PRD.md; no `skip`/`skipif`/`xfail` markers anywhere.

## Step 6: Generate Implementation — 2026-08-12T21:50:00.000Z

Both success and error envelopes match the scaffold's `response_envelope` exactly. The implementation is complete and verified.

## Summary

Generated a complete Python + Flask implementation for the Vault Cash & Federal Reserve Currency Ordering API at `/home/ubuntu/github/CodingPRD/tasks/task_1299_vault_cash_federal_reserve_currency/workspace/implementation/`.

**Result: 82/82 tests pass under `prd-bench-local-run --isolation per-test-server`** (the full suite including all OCC, state-machine, calculation, cascade, and boundary tests).

### File list
- `start.sh` — foreground launcher; guarded `pip install` (no-op when flask present); `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, error handlers, SIGTERM fast-exit handler for rapid per-test restarts
- `db.py` — in-memory store (starts empty; no seeding), logical clock defaulting to `2026-08-01T00:00:00Z`
- `errors.py` — `ApiError` carrying `error_id`/`http_status`/`message`
- `response.py` — envelope helpers (`meta`/`response_type`/`data`; pagination fields `limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, entity-backed identity resolution (StaffMember/Carrier), site-scope and carrier-ownership checks
- `util.py` — parsing, `round_half_up_cents` (Decimal), pagination (default 10, min 1, max 100)
- `services.py` — ledger append + site recompute cascade, posture derivation, recon refresh, order totals, ATM posture, seasonal-window lookup
- `routes/` — 13 modules: `admin` (clock), `sites`, `staff`, `carriers`, `atms`, `seasonal`, `fed_orders`, `shipments`, `fitness`, `counterfeit`, `ledger`, `recons`, `forecasts`

### Endpoints
**64 API endpoints implemented** — every row in the scaffold's endpoint table (all 63 business/resource endpoints plus `POST /vault-cash/_clock/set_current_utc`).

### Notable design decisions
- **Ledger-driven recompute**: `on_hand_fit/unfit` are recomputed by replaying the site's append-only ledger on every entry; exposure fields (`reserved_out`/`in_transit_inbound`/`pending_inbound`) are maintained incrementally, then `on_hand_total`, `insurance_headroom`, and `posture` re-derive, followed by the recon refresh sweep.
- **Pinned fee rounding**: per-line `round_half_up(line_cents/160)` then sum (the 63+63=126 vs 125 counter-example is honored).
- **Validation precedence tuning** (driven by test expectations): at Fed-order submit the ORDER headroom guard is evaluated before the FROZEN cross-entity guard, and FROZEN before the vault-limit guard — so a site frozen by exhausted headroom reports `ERR_INSURANCE_HEADROOM_EXCEEDED`, while a site born at the vault limit (ample headroom) reports `ERR_VAULT_FROZEN`. At shipment create, inbound insurance headroom (priority 10) is checked before carrier liability (priority 18) per the scaffold's priority order.
- **Turnaround half-open boundary**: conflict iff `new_dep < s_arr + 45m AND s_dep < new_arr + 45m`, so an exactly-45-minute gap is permitted.
- **Cancel compensation**: cancelling from SCHEDULED releases `reserved_out`; from LOADED the reservation was already consumed at load, so only the `SHIPMENT_IN` reversal returns value (no double-decrement of `reserved_out`).
- **OCC field names** read from the scaffold: `expected_vault_site_version` (site PATCH), `expected_fed_order_version` (line add), `expected_atm_version` (forecast publish) — each returning the scaffold's exact 412 error ID.
- **Missing error ID**: the scaffold catalog omits a not-found ID for ledger entries; used `ERR_CASH_LEDGER_ENTRY_NOT_FOUND` (404) following the naming pattern.
- **Test-helper fix (outside implementation)**: added a `"peer"` label (second VaultCustodian) to `test_helpers/fixtures.py:create_staffed_site` — the existing test `test_counter_cannot_lock_peer_locks` requests it and would otherwise `KeyError`; this was a test-infrastructure gap, not an implementation change.

One operational note: under heavy concurrent host load (load average spiked to 47 from other pipelines running on this shared host), the harness occasionally loses a random test to a *setup-phase restart timeout* (never an assertion failure). A `SIGTERM` fast-exit handler was added to `app.py` to make restarts near-instant; with it, clean 82/82 rounds are the norm when the host isn't saturated.

## Step 7: Run Tests and Iterate — 2026-08-12T22:05:00.000Z

All 8 parallel rounds pass cleanly with zero failures. The sweep is stable — exit condition met.

## Summary

- **Iterations run**: 1 (single 8-round parallel stability sweep; no fixes needed).
- **Results**: All 8 rounds `passed == total` (82/82 each round), zero non-passing entries across the union of all rounds. No flakiness, no setup-phase restart timeouts, no assertion failures observed despite concurrent host load (some harness `Killed` log lines appeared in interim output from OOM-pressure on the shared host, but every round's final results file recorded 82/82).
- **Tests deleted**: None.
- **Fixes applied to `test_helpers/`**: None in this session. (Per `worklog.md`, a prior session added a `"peer"` VaultCustodian label to `test_helpers/fixtures.py:create_staffed_site` required by `test_counter_cannot_lock_peer_locks`; verified still present and passing.)
- **Fixes applied to `implementation/`**: None in this session. The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1299_vault_cash_federal_reserve_currency/workspace/implementation/` (Flask, in-memory store, 64 endpoints, ledger-driven recompute, SIGTERM fast-exit for per-test-server restarts) was already conformant from a prior iteration and held stable across all 8 concurrent rounds.

Task state: **green and stable** — no diagnostic protocol steps (0–3) were triggered since the failure union was empty.

## Step 8: Finalize PRD — 2026-08-12T22:05:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite fixes, 0 test_helpers fixes, and 0 implementation fixes.

## Step 9: Complete PRD — 2026-08-12T22:15:00.000Z

All done. Final verification passed — 20 diff hunks, all applied cleanly. Here is the summary.

## Summary

**Source:** `workspace/PRD.md` (no PRD_FINALIZED.md existed) → `workspace/PRD_COMPLETED.md`
**Size:** 318 → 320 lines; 54,079 → 57,925 bytes (+3,809 chars / +3,846 bytes).
**Counts:** 20 changes total — 10 ambiguity-pins, 10 mismatch-revisions. No new sections; all edits are in-paragraph inserts/revisions or table-row insertions.

### Changes (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref)

1. §2.1 — insert — ambiguity — List endpoints apply site scope as a filter (not rejection) for the four site-scoped staff roles; a shipment belongs to a site via origin *or* destination; `CashOperationsAdmin`/`CarrierDispatcher` lists unfiltered; carrier list never scope-filtered — `routes/sites.py:92-94`, `routes/shipments.py:212-217`, `routes/carriers.py:44-52`
2. §2.3 — insert — ambiguity — Negative/non-integer `offset` (and non-integer `limit`) rejected with `ERR_INVALID_REQUEST`; equality-filter query params accepted, undefined params ignored; `created_at` ties broken by creation order — `util.py:111-133`, `routes/sites.py:95` (`_seq` tiebreak)
3. §2.4 — revise — mismatch — Clock advance re-derives posture at *every* vault site (not only SEIZED-holding sites), each bumping `updated_at`/`version`; response `data` echoes `current_utc` — `routes/admin.py:23-27`
4. §2.5 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock — `services.py:32-44` (`clock_iso_ms`), `db.py:48-51`
5. §2.7 — insert — ambiguity — Site-patch version check evaluated before any patched field is validated/applied — `routes/sites.py:112-134`
6. §2.8 — revise — mismatch — Site-scope/carrier-ownership moved to *after* path-id and body-FK existence checks (impl resolves 404s before scope everywhere) — e.g. `routes/sites.py:100-105`, `routes/fed_orders.py:96-100`
7. §3.2 — insert — ambiguity — Line-add OCC version check fires before the DRAFT-state check and denomination-mix rules — `routes/fed_orders.py:104-118` (impl's own flagged choice)
8. §3.2 — revise — mismatch — Submit guard order pinned to impl: DRAFT-state → `ERR_ORDER_HAS_NO_LINES` → cutoff → direction fork (`ORDER` headroom / `DEPOSIT` sufficiency) → FROZEN → `ORDER` vault-limit (was: FROZEN before cutoff and before direction guards) — `routes/fed_orders.py:188-241`
9. §3.4 — revise — mismatch+ambiguity — Scheduling guards evaluated carrier-ACTIVE → headroom → turnaround → dock → liability (not the liability-first description order); "inbound" = any shipment with a destination site (inter-site transfers included) for headroom/dock guards; `carrier_id` resolved before the schedule-shape check, linked order/sites after; scope checked against order's site or origin (else destination) — `routes/shipments.py:100-168`
10. §3.4 — insert — ambiguity — `accept_variance` defaults to `false`; EXCEPTION-state verify without it → `ERR_SHIPMENT_INVALID_STATE`; accepted variance books the counted value recorded at exception time — `routes/shipments.py:313-337`
11. §3.4 — revise — mismatch — Cancellation: `reserved_out_cents` decreases only from SCHEDULED (load already released it); LOADED-cancel posts the `SHIPMENT_IN` reversal; inbound cancel from SCHEDULED moves nothing, from LOADED releases destination `in_transit_inbound_cents` — `routes/shipments.py:408-433`
12. §3.5 — revise — mismatch+ambiguity — Escrow is a negative `FITNESS_RECLASS` entry against UNFIT on the clock date; FROZEN guard fires *before* the unfit-balance check — `routes/fitness.py:39-46,59-62`
13. §3.5 — insert — ambiguity — A zero-valued bucket posts no ledger entry at settle — `routes/fitness.py:164-175`
14. §3.6 — insert — ambiguity — Direct-detection validation: bad denomination or `note_count` < 1 → `ERR_INVALID_REQUEST` (400); optional `fitness_batch_id` resolved after those field checks, unknown → `ERR_FITNESS_BATCH_NOT_FOUND` — `routes/counterfeit.py:40-52`
15. §3.7 — revise — mismatch — Dropped "unique" from `terminal_code` (impl enforces no uniqueness) — `routes/atms.py:30-37`
16. §3.8 — insert — ambiguity — Tolerance boundary pinned: absolute variance ≤ 1000 balances (exactly 1000 still BALANCED); OPEN-recon refreshes update `final_expected_cents` without version bump, counted-recon refreshes bump version — `routes/recons.py:119-122`, `services.py:194-206`
17. §3.8 — revise — mismatch — Locking records the acting identity in `approved_by_staff_id` for both BALANCED and APPROVED closures (overwriting a prior approver), not only "when closing a balanced reconciliation" — `routes/recons.py:178-180`
18. §4 — revise — mismatch — Endpoint-table path param `{id}` → `{orderId}` on the lines-list row (per §2.5 naming) — impl route `routes/fed_orders.py:169`
19. §5 — insert — mismatch — Added missing catalogue row `ERR_CASH_LEDGER_ENTRY_NOT_FOUND | 404` (the ledger-entry not-found ID) — `routes/ledger.py:62-65`
20. §5 — insert — ambiguity — Added `ERR_INTERNAL | 500` (unexpected-exception fallback envelope) — `app.py:38-40`

**Left out of scope deliberately:** the SIGTERM immediate-exit handler (`app.py:12-18`) and unknown-route → `ERR_INVALID_REQUEST` 400 fallback (`app.py:30-36`) — operational harness behavior, not API semantics.
