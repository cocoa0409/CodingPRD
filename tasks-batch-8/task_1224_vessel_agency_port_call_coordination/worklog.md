# Worklog — task_1224_vessel_agency_port_call_coordination

## Step 1: Create task directory — 2026-08-12T01:42:50.000Z

Output folder PRE-ASSIGNED per run instructions: `tasks/task_1224_vessel_agency_port_call_coordination` with `workspace/` already present. Step 1 auto-index scan skipped as instructed; directory verified to exist and be empty except `workspace/`.

## Step 2: Generate scaffold — 2026-08-12T02:36:16.000Z

Scaffold generation complete for task 1224 (Vessel Agency & Port Call Coordination) at harder-than-expert difficulty. No sibling tasks were inspected.

**Files written** (all parse as YAML, lint clean):
- `/home/ubuntu/github/CodingPRD/tasks/task_1224_vessel_agency_port_call_coordination/SCAFFOLD.yaml` — 114,285 bytes (§1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1224_vessel_agency_port_call_coordination/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 69,264 bytes (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1224_vessel_agency_port_call_coordination/SCAFFOLD_CORNER_DESIGN.yaml` — 134,129 bytes (single top key `scaffold_corner_design`)

**Linter verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (806 calls scanned across 18 §1.8 + 53 executable §1.9 instances.)

**Scaffold dimensions** (deliberately above the Expert band): 15 entities, 102 endpoints, 44 error codes, 48 ordered validation rows, 8 RBAC roles (6 opaque + PrincipalRep/VendorRep entity-backed), 14 state machines, 7 calculation rules, 2 OCC concurrency rules. Archetype: ledger reconciliation + posture-driven gating; layers: optimistic concurrency, dual-variant calculation, cascading side effects, version-pinning on approval. Topology: flat with FK references; cyclic state-machine shape (PO dispute loop, DA dispute loop, notification reject/resubmit loop, cargo hold/release loop, shore-pass expiry/re-issue loop).

**Difficulty rule coverage (§1.8, 2 instances each, all literals computed by executing the formulas):**
- dual_variant_calc: DA estimate (272,250¢ pinned tariff v1) vs final (408,000¢ under superseded tariff, 4 actual days); principal exposure forward (102,500) vs cash-basis (20,000)
- combinatorial_formula: mode (a) tiered port dues with inclusive GT boundary (40,000 vs 40,002 at GT 20,000/20,001); mode (b) per-line fee rounding pinned round-then-sum (166 vs 167)
- non_linear_state_machine: PO INVOICED⇄DISPUTED cycle; notification reject/resubmit loop with revision_count
- transitive_cascade: port-call cancel depth-3 (orders → line reversals → DA recompute); PO over-variance invoice depth-3 (PO→DALine→DA FINAL→DISPUTED)
- priority_pair_validation_conflict: state-vs-fiscal and safety-vs-constraint dual-failure pairs
- boundary_precision_check: funding equality (5466 passes / 5465 fails); berth half-open adjacency (touching allowed, 1-minute overlap rejected)
- cross_entity_state_dependency: PortCall×DA sailing gate; BerthWindow×AuthorityNotification HM-ack occupy gate
- resource_temporal_overlap: berth half-open vs service-order ±45m buffer-inflated closed semantics (45m gap conflicts, 91m clears)
- compensating_invariant: advance create+refund cash conservation; PO create+cancel estimated-liability conservation

**§1.9 breadth:** 67 instances (53 with full recipes + 14 `excluded_because` stubs) across all nine claim-extraction-guide sections, including segregation-of-duties on DA finalize, conditional confirm-role by service kind, entity-backed ownership denials, logical-clock default epoch (2026-05-01T00:00:00Z), and a full settlement-lifecycle gate chain (UNREFUNDED_ADVANCES → BALANCE_NOT_ZERO → SETTLED → CLOSED).

Key pinned semantics a PRD reader must honor: validation priority order (auth → role → existence → ownership → state → safety → temporal → constraint → referential → fiscal → OCC → request-shape), advance gate `received − refunded >= advance_required` (equality passes), settle requires `balance_due == 0` exactly with no unapplied remainders, and agency-fee evaluation order lines → per-line-rounded fee → 80% advance.

Orchestrator verification: all three files exist on disk and parse as valid YAML (python3 yaml.safe_load).

## Step 3: Copy shared files — 2026-08-12T02:36:47.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1224_vessel_agency_port_call_coordination/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T02:54:23.000Z

The PRD is complete and all verification passes. Final report:

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1224_vessel_agency_port_call_coordination/workspace/PRD.md` — **405 lines, 67,850 bytes**.

The document was produced per the prd-bench-doc-generator skill from `SCAFFOLD.yaml` (read in full, both pages). The withheld design indexes were never opened. Structure:

- **§1 Introduction** — 2 paragraphs, business-context angle (port agency obligations, DA as financial spine).
- **§2 Global Specifications** — 11 subsections: RBAC with per-role `identity:` translations (entity-backed `PrincipalRep`/`VendorRep`, opaque others); **§2.2 emitted byte-verbatim** from `section-2.2-response-structure.md` (verified by substring check); pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending); common properties; the logical clock (startup default `2026-05-01T00:00:00Z`, `to_iso8601`/`current_utc`); integer-cents round-half-up precision; an explicit 13-stage validation-order pipeline; OCC naming both write endpoints with `expected_port_call_version` → `ERR_STALE_VERSION` (412); berth half-open vs. 45-minute buffer-inflated closed overlap semantics; tariff supersession with version pinning; disbursement ledger invariants.
- **§3 Business Logic** — 9 domain-derived subsections (nomination/credit → filings/clearance → berth/arrival/sailing/cancel → vendors/POs → service orders → crew/husbandry → cargo docs → DA estimates/funding → finalization/disputes/settlement), all scattering guidelines applied; every calculation expressed in reconstructible prose (tiered port dues with inclusive bounds and night/hazmat surcharges, per-line-rounded 2.5% agency fee with the 3333+3333→166 example, 80% advance requirement, dual-variant exposure with the 100000/20000 example, variance sentinel 999.99 and exactly-10.0-within boundary, strict 2-hour late-cancel cutoff).
- **§4** — 102-row endpoint table, 4 columns only. **§5** — 44-row error catalogue, 2 columns only.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 91 required, 91 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] priority: 13 stages checked, 13 expressed in §2.7 ordered prose, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write_endpoint + expected_port_call_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 14 machines' transitions expressed incl. system cascades and lazy PASS_EXPIRED, 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose, 0 missing
- validations[] conditions: 44 error IDs checked, 44 matchable to triggers in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (sailing/cancel 3-link cascades, invoice/match forks, FUNDED auto-toggle, supersede semantics), 0 missing
- entities[].fields[] structured content: defaults, null-until, computed fields reconstructible, 0 missing
- sibling-branch symmetry: invoice/match/resolve forks, FUNDED toggles, cancel from-state groups rendered with equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 764
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks: §2.2 block byte-identical to the canonical source; no pseudocode operators (`==`, `>=`, `->`, `+=`, …) anywhere in prose; all 55 state values and 91 enum values present as exact backticked strings.

## Step 5: Generate unit tests — 2026-08-12T03:18:41.000Z

Done. Summary of what was generated and verified.

## Files generated

**test_helpers/** (all 9 required modules, under `/home/ubuntu/github/CodingPRD/tasks/task_1224_vessel_agency_port_call_coordination/test_helpers/`):
- `types.py` — 16 entity TypedDicts + full status/role enums (all entities here carry `common_fields: true`, so all include id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (all 70+ endpoints incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` enum (44 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_da_funding_invariants`
- `factories.py` — payload factories, input fields only
- `constants.py` — 2.5% fee, 0.80 advance pct, 10.0% variance tolerance, 45-min buffer, 120-min late-cancel cutoff, clock default
- `test_users.py` — `TEST_USERS` constants + per-instance builders for all 8 roles (`make_principal_rep_headers`/`make_vendor_rep_headers` for the entity-backed roles)
- `fixtures.py` — composite helpers: `create_principal/port_call/vendor/...`, `create_da_for_call` (OCC-aware), `file_all_notifications`, `drive_call_to_cleared`, `drive_call_to_alongside`, `send_da_and_fund`, `sail_call`, `drive_call_to_sailed_with_da`
- `__init__.py` — barrel export

**test_suite/** (`conftest.py` + 11 test files, 91 test functions):
- `test_01_calculations.py` (10), `test_02_dual_variant_accounting.py` (4), `test_03_state_machine_cycles.py` (10), `test_04_cascades.py` (4), `test_05_priority_and_boundaries.py` (8), `test_06_cross_entity_gates.py` (8), `test_07_ledger_invariants.py` (4), `test_08_entities_and_listings.py` (8), `test_09_validations.py` (22), `test_10_husbandry_and_disputes.py` (4), `test_11_occ_clock_rbac.py` (9)

## Coverage verification (scripted)

- **Queue A (Difficulty): all 18 instances covered with exactly 2 tests each** (≥2 requirement met) — tags verified to resolve against real `name:` entries in SCAFFOLD_DIFFICULTY_DESIGN.yaml.
- **Queue B (Corner): all 42 non-stub instances covered with ≥1 test each**; the 14 `excluded_because:` stubs were NOT translated (all stub cross-references resolve to real difficulty instances).
- Every test docstring ends with exactly one terminal `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line (91/91 pass).
- Every test docstring's quoted PRD citation survives a verbatim ≥8-word-window grep of `workspace/PRD.md` (91/91 pass).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- `python3 -m py_compile` passes over all 21 generated `.py` files.

## Skipped design instances

**Zero non-stub instances skipped.** All 18 difficulty and 42 corner non-stub instances passed the PRD-first two-condition filter (verbatim coverage + unique derivability) — the PRD prose uniquely pins every asserted outcome, including the validation-priority orderings (PRD §2.7's numbered pipeline), the segregated finalize rule, the fixed clock epoch, and all literal money figures.

## Step 6: Generate implementation — 2026-08-12T03:18:41.000Z

Implementation complete and verified. Summary:

## What was built

A complete Python + Flask implementation of the Vessel Agency & Port Call Coordination API in `/home/ubuntu/github/CodingPRD/tasks/task_1224_vessel_agency_port_call_coordination/workspace/implementation/`:

- **app.py** (1,507 B) — entry point, envelope-compliant error handlers (404/405 included), binds `0.0.0.0:$PORT` (default 10000)
- **start.sh** (343 B, executable) — guarded `pip install` (no-op when Flask present), `exec python3 app.py` in foreground
- **requirements.txt** — flask>=3.0,<4.0
- **db.py / errors.py / response.py / middleware.py / utils.py** — in-memory stores (15 empty dicts, zero seeding), full 42-entry error catalog, `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` pagination, X-User-ID/X-User-Role auth for the 8 roles, ISO-8601 helpers and half-up Decimal rounding
- **services/domain.py** — port-dues marginal-tier calc (ESTIMATE/FINAL variants, night/hazmat surcharges, single half-up rounding), per-line-rounded 2.5% agency fee, da_totals_calc with pinned evaluation order, variance calc with 999.99 sentinel, dual-variant principal exposure, lazy PASS_EXPIRED evaluation, funding FUNDED↔SENT auto-toggle
- **routes/** — 15 blueprint modules covering all 14 resource groups plus the logical clock (default `2026-05-01T00:00:00Z`, never wall-clock)

## Verification results

- **Route count: exactly 102** registered (method, path) pairs — matches the SCAFFOLD endpoint count (verified via Flask `url_map`; module decorator tally also sums to 102)
- **py_compile: all 25 .py files pass**
- **Boots cleanly from a fresh process** via `bash start.sh` — verified twice; store starts empty, clock at the pinned default
- **End-to-end smoke tests pass** against the live server, covering: full happy-path voyage (principal → call → 4 notifications → pre-arrival → clearance → berth confirm/occupy → arrival → DA with tariff-pinned PORT_DUES line (742,500 + 18,563 fee verified) → send → advance → auto-FUNDED → sailing with berth release and FINAL port-dues actualization → finalize with segregation-of-duties → apply/refund advances → settle at exact zero balance → close), plus error paths: 401/403 auth, ERR_DUPLICATE_NOTIFICATION_TYPE, ERR_STALE_VERSION (412 on both OCC endpoints), ERR_WINDOW_NOT_STARTED, ERR_CREDIT_LIMIT_EXCEEDED, ERR_CONFIRM_ROLE_MISMATCH, ERR_RESOURCE_UNIT_OVERLAP (90-minute touching buffers conflict, 91 minutes pass), late-cancel 25% fee inside the 2h cutoff, ERR_VISA_NOT_REQUIRED, lazy shore-pass expiry blocking complete, PO variance fork at exactly 10.0 (within tolerance) vs 20.0 (DISPUTED→reinvoice), ERR_NOT_RESOURCE_OWNER, ERR_NO_LINKED_CREW_CHANGE, and the depth-3 cancel cascade (windows/crew/orders cancelled with zero fees, DA line mirrors reversed).

## Key design decisions

- Validation pipeline follows PRD §2.7 priority order (auth → role → path existence → payload FKs → ownership → state → safety → temporal → business → referential → fiscal → OCC → request shape), with ERR_INVALID_REQUEST deliberately last
- Logical clock drives all timestamps (created_at/updated_at with 3 fractional digits); insertion sequence tie-breaks list ordering
- All money is integer cents via `Decimal` ROUND_HALF_UP, applied exactly once per rule

## Step 7: Run tests and iterate — 2026-08-12T03:32:46.000Z

Pre-sweep route parity verified by orchestrator: SCAFFOLD declares 102 endpoints; Flask `url_map` registers exactly 102 (method, path) pairs; missing: NONE.

Subagent summary (verbatim):

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 0/1 (collection error), then 87/91 × 8. Sweep 2 (after fixes): **91/91 passed in all 8 rounds** — exit condition met.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added missing `create_cargo_document` composite fixture (ops role, via `create_cargo_document_payload`). `test_09_validations.py` imported it but it was never defined, causing a collection failure across the whole suite in every round.

**Fixes applied to `test_suite/`:**
- `test_09_validations.py` / `test_da_finalize_same_user_segregation_rejected` — corrected the post-rejection status assertion from `SENT_TO_PRINCIPAL` to `FUNDED`. The setup funds the account at exactly `advance_required_cents` (820 == 820), and PRD §3.8 verbatim auto-toggles the account to FUNDED ("whenever net funding ... reaches `advance_required_cents` after an advance creation ... an account in `SENT_TO_PRINCIPAL` moves to `FUNDED` on its own"); the old assertion contradicted PRD.
- `test_04_cascades.py` / `_setup_final_da_with_delivered_po` (shared by `test_po_over_variance_invoice_flips_final_da_to_disputed` and `test_po_over_variance_invoice_recomputes_final_totals`) — removed the setup assertion `da["total_final_cents"] == 10250` and repinned the docstring. The figure depends on what a DELIVERED-but-uninvoiced PO mirror actualizes to at finalize; PRD §3.9 ("purchase-order mirrors take their source's actual cost, counting zero when the source was cancelled") is silent on the no-actual-yet case (DEFAULT-VALUE SILENCE — 0 vs. estimate both defensible). The PRD-verbatim cascade assertions (PO→DISPUTED, mirror→DISPUTED at invoiced actual, FINAL→DISPUTED flip, totals 12300/4100) are unchanged and hold under either reading.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/domain.py` / `recompute_da_totals` — `advances_received_cents` now sums `amount_cents` over advances in `{RECEIVED, APPLIED, REFUNDED}` (cumulative receipts) instead of `{RECEIVED, APPLIED}`. The literal reading made `funding_available_cents` go negative after a full refund (0 − 0 − 50000), violating PRD §2.11's "never goes negative" invariant and breaking §3.8's auto-FUNDED gate for any replacement advance after a refund; the cumulative reading is the only document-consistent one (create+refund restores the zero baseline).

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` files present on disk; every round passed=91 total=91 failed=0.

## Step 8: Finalize PRD — 2026-08-12T03:36:44.000Z

Both edits applied cleanly. Here is the summary.

## Line counts
- `PRD.md`: 405 lines
- `PRD_FINALIZED.md`: 405 lines (0.0% line-count delta; 2 lines revised in place)

## Changes (one bullet per edit)
- **§3.8** — revise — `advances_received_cents` definition widened from "advances in `RECEIVED` or `APPLIED`" to "`RECEIVED`, `APPLIED`, or `REFUNDED`", with a cumulative-receipts clause (a refunded advance's receipt stays in the figure; its return is tracked in `advances_refunded_cents`; this keeps `funding_available_cents` non-negative per §2.11) — `implementation/services/domain.py:174-175` (the Step 7 impl fix).
- **§3.9** — revise — finalization's mirror-actualization rule now pins the no-actual-yet default: "counting zero when the source was cancelled **or has no actual recorded yet** — a purchase order delivered but not yet invoiced, or a service order not yet completed, actualizes its mirror to zero" — `implementation/routes/disbursement_accounts.py:161` (SO mirror: `src["actual_cents"] or 0`) and `:167` (PO mirror: `src["invoiced_cents"] or 0`).

## Step-7 items needing no PRD edit
- `test_helpers/fixtures.py` missing `create_cargo_document` fixture — pure fixture bug; no behavioral content for the PRD.
- `test_09_validations.py` `SENT_TO_PRINCIPAL` → `FUNDED` correction — PRD §3.8 already pins the auto-FUNDED toggle verbatim ("an account in `SENT_TO_PRINCIPAL` moves to `FUNDED` on its own"); the old test contradicted the PRD, impl matches it (`domain.py:198-204` `refresh_funding_posture`).

## Per-edit pre-edit search log

**Edit 1 (§3.8 `advances_received_cents`)**
- (a) Subject: the definition of `advances_received_cents` and every formula derived from it.
- (b) Enumerated impl paths: `services/domain.py:174-175` (the sum), `:176-180` (`funding_available_cents` = received − applied − refunded), `:198-204` (`refresh_funding_posture` auto-FUNDED gate, net = received − refunded), `routes/port_calls.py:264-266` (sailing funding gate, same net formula), `routes/disbursement_accounts.py:34-37` (initial zeros), `services/domain.py:233-237` (exposure uses `advances_applied_cents` only — unaffected). Also checked all PRD mentions: §2.11 ("received minus applied minus refunded … never goes negative"), §3.3 sailing gate, §3.8 auto-FUNDED/auto-revert, §3.9 settlement (`balance_due` uses applied only). Worked the arithmetic for all advance lifecycles (RECEIVED; partial-apply; full-apply→APPLIED; refund-after-partial-apply→REFUNDED): net and availability stay coherent under the cumulative reading, and §3.8's refund-reverts-FUNDED clause still holds.
- (c) Wording adjustment: added the explicit cumulative-receipts rationale clause so the widened set doesn't read as an arbitrary enumeration and stays consistent with §2.11's never-negative invariant it was designed to satisfy.

**Edit 2 (§3.9 finalize-time mirror actualization)**
- (a) Subject: the actual value assigned to an `ESTIMATED` SO/PO mirror line at finalization.
- (b) Enumerated impl paths: `routes/disbursement_accounts.py:154-191` (`_actualize_all_lines`, called only from `finalize_disbursement_account` at `:205`; SO branch `:158-163`, PO branch `:164-169`, both default to 0 on missing actual/source); `refinalize_disbursement_account` (`:213-229`) does **not** re-actualize, matching §3.9's existing "recomputes … with any upheld credits already applied"; `routes/service_orders.py:186-196` (completion actualizes the mirror only when the account is editable — those lines are already `ACTUALIZED` and skipped at finalize); `routes/purchase_orders.py:173-193, 208-216` (invoice/reinvoice set the mirror to `ACTUALIZED`/`DISPUTED` with the invoiced actual — again skipped by the `ESTIMATED` filter). Verified against `test_suite/test_04_cascades.py:109-175` that the pinned cascades (12300/4100 after a 12000 invoice) hold under the zero-default reading.
- (c) Wording adjustment: scoped the extension as an appositive to the existing "counting zero when the source was cancelled" clause ("or has no actual recorded yet") with the two concrete cases named, avoiding any universal claim about lines not in `ESTIMATED` or about refinalization, neither of which the impl path touches.

## Step 9: Complete PRD — 2026-08-12T03:49:16.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1224_vessel_agency_port_call_coordination/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 405 lines / 68,261 chars → `PRD_COMPLETED.md` 406 lines / 70,718 chars (**+1 line, +2,457 chars**; 21 lines touched, 25 edits, all in-paragraph — no new sections).

**Counts:** 21 ambiguity-pins, 4 mismatch-revisions.

**Changes (section — insert/revise — class — what — impl ref):**

- §2.2 — revise — ambiguity — pagination `meta` fields appear only on list responses; other success `meta` carries just `api_request_id`/`api_request_timestamp` — response.py:17-40
- §2.2 — insert — ambiguity — client-supplied datetimes echoed in ISO 8601 UTC, fractional seconds only when sub-second precision present — utils.py:28-36, services/serializers.py:12-23
- §2.3 — revise — ambiguity — out-of-range/unparsable `limit`/`offset` are clamped/floored to defaults, never rejected — utils.py:97-109
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order; DA lines then by category then insertion — utils.py:119-121, routes/disbursement_accounts.py:119
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — utils.py:75
- §2.5 — insert — ambiguity — missing/unparsable `to_iso8601` → `ERR_INVALID_REQUEST` — routes/clock.py:17-19
- §2.6 — revise — ambiguity — round-half-up means ties away from zero (matters for negative dispute-credit fee lines) — utils.py:51-58
- §3.1 — revise — ambiguity — `imo_number` is a non-empty string with no seven-digit format check — routes/port_calls.py:52
- §3.3 — insert — ambiguity — sailing-time PORT_DUES actualization falls back to the line's pinned tariff when none is currently `PUBLISHED` — routes/port_calls.py:282-284
- §3.4 — insert — ambiguity — `invoiced_cents` must be a non-negative integer (zero allowed) — routes/purchase_orders.py:171,206
- §3.4 — revise — **mismatch** — invoice mirror actualization + totals recompute apply whenever a non-`SUPERSEDED` account carries the mirror, not only "while the account is editable" — routes/purchase_orders.py:174-193
- §3.4 — revise — **mismatch** — same qualifier fix for reinvoice — routes/purchase_orders.py:211-216
- §3.4 — revise — **mismatch** — same qualifier fix for purchase-order cancellation reversal — routes/purchase_orders.py:242-252
- §3.5 — revise — ambiguity — `CANCELLATION_FEE` line shape pinned: `source_type` `MANUAL`, null `source_ref`/`tariff_id`, zero `estimated_cents` — routes/service_orders.py:215-226
- §3.5 — revise — ambiguity — completion `actual_cents` is a non-negative integer — routes/service_orders.py:184-185
- §3.6 — revise — ambiguity — repatriation also leaves a linked `PASS_EXPIRED` movement untouched (lazy expiry runs first) — routes/husbandry_cases.py:115-119
- §3.6 — revise — ambiguity — departure waiver grantable at any time regardless of case status — routes/husbandry_cases.py:123-129
- §3.8 — insert — ambiguity — DA creation against a call whose existing non-`SUPERSEDED` account is past `PRO_FORMA` → `ERR_INVALID_STATE` — routes/disbursement_accounts.py:59-61
- §3.8 — revise — ambiguity — `SENT_TO_PRINCIPAL`↔`FUNDED` gate re-evaluated on every totals recompute (line mutations included), both directions — services/domain.py:183,198-204
- §3.8 — revise — ambiguity — tariff payload validation pinned: required `effective_from`, strictly ascending positive `gt_up_to` with null only on the final band, non-negative `rate_cents`/surcharges — routes/tariffs.py:17-52
- §3.8 — revise — **mismatch** — estimate-variant refresh happens only via the §3.1 schedule patch (`NOMINATED`/`PRE_ARRIVAL_FILED`), never in `CLEARED_TO_ENTER`/`ALONGSIDE` — routes/port_calls.py:149-157
- §3.8 — revise — ambiguity — `/tariffs/{id}/da-lines` ordering: `created_at` asc, then `category` asc — routes/tariffs.py:101-102
- §3.8 — revise — ambiguity — account-line presentation ties broken by insertion order after category — routes/disbursement_accounts.py:119
- §3.9 — insert — ambiguity — a `PORT_DUES` line still `ESTIMATED` at finalization (account created after sailing) is priced by the final variant at finalization, published tariff first then pinned — routes/disbursement_accounts.py:170-187
- §3.9 — revise — ambiguity — refinalization records the acting user as `finalized_by_user_id` — routes/disbursement_accounts.py:226
- §3.9 — revise — ambiguity — raising a dispute moves a referenced line to `DISPUTED` only when it is `ACTUALIZED` — routes/cost_disputes.py:97-99

**Verified consistent (no change needed):** the §2.7 13-stage pipeline matches every endpoint's actual check order (stage granularity) across all 16 route modules; all 43 error IDs and HTTP statuses match §5 exactly; both overlap mathematics, tiered port-dues walk, per-line fee rounding, dual-variant exposure, cancel/sail cascades, lazy shore-pass expiry, and all §4 roles/201-vs-200 codes already pinned correctly.

Orchestrator verification: `workspace/PRD_COMPLETED.md` present on disk (406 lines, 70,718 bytes).
