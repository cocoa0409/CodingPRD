# Worklog — task_1722_import_sourcing_buying_agent_services

## Step 1: Create Task Directory — 2026-08-14T11:26:00.000Z

Task directory `tasks/task_1722_import_sourcing_buying_agent_services/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation args. No index scan performed, no other task_* directory touched.

User directive: "Generate task hard than expert level!" — forwarded to scaffold generation step.

## Step 2: Generate Scaffold — 2026-08-14T12:32:00.000Z

## Scaffold generation complete — task_1722_import_sourcing_buying_agent_services

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 60 endpoints, 14 entities, 18 §1.8 instances, 56 §1.9 instances, 969 calls scanned, 0 violations.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/SCAFFOLD.yaml` — §1.0–§1.7 (fixed response envelope verbatim; 14 entities, 11 state machines, 7 calculation rules, 11 ordered validation priorities, 60 endpoints, 55 error codes, 6 roles)
- `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 18 instances, exactly 2 per each of the 9 difficulty rules, all with structured `setup_api_calls`/`trigger`/`assert` chains and code-computed literal asserts (e.g., screening 92 vs onsite 87 on identical audit inputs; provisional 25,000 vs final 20,000 commission after a tier shift; per-line chargeback 51 vs 50 rounding divergence)
- `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/SCAFFOLD_CORNER_DESIGN.yaml` — 56 corner instances across all nine claim-extraction sections (entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, consistency)

**Design highlights (harder-than-expert directive):**
- Archetype: multi-party negotiation × workflow orchestration; cyclic state machines on Sample (revision loop, cap 3) and Quotation (alternating counter rounds, cap 6, strict wrong-party guard); parallel state dimensions on PurchaseOrder (production × latest_psi_result × document_status).
- Two OCC concurrency rules (quotation counter, PO amend) with `expected_*_version` placeholders only.
- Depth-3 cascade (claim approval → factory debit → SUSPENDED → quotations EXPIRED + unshipped POs CANCELLED) and depth-2 cascade (clock sweep → doc EXPIRED → posture NON_COMPLIANT → ship_blocked).
- Distinct temporal-overlap semantics: inspector half-open interval clash vs factory aggregate monthly-capacity bucket (inclusive `<=` at exactly 1000).
- Segregation of duties with entity-backed identities: the PO's assigned agent is forbidden from adjudicating its claims (peer agent required); ComplianceOfficer (opaque) alone approves audits/documents.
- Boundary pins verified by Python computation: GMV tier edge at exactly 10,000,000 (4% vs 5%), AQL Ac/Re at 3/4 for n=50, chargeback penalty tiers at 0.0500/0.1000, suspension threshold inclusive at exactly 1,000,000, claim window inclusive at delivered_at + 30 days.
- Logical clock endpoint with mandated startup default `2026-08-01T00:00:00Z`, driving quotation expiry, document expiry sweeps, and the claim window.

**Audits performed beyond lint:** placeholder closure (0 unbound `${var}` across 969 calls), instance-name uniqueness across both files (74 unique), error-catalog closure (no undeclared used codes; NOT_FOUND codes all covered by the priority-4 template rule), enum-value closure (removed unreachable Buyer.CLOSED and SUSPENDED→ACTIVE), trigger↔side-effect bidirectional match for all 7 calculations, and manual call-by-call state replay of the trickiest chains (priority-conflict ordering, cascade preconditions, posture flip timing).

## Step 3: Copy Shared Files — 2026-08-14T12:33:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1722_import_sourcing_buying_agent_services/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T12:40:00.000Z

All contracts pass. PRD generated.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/workspace/PRD.md`

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields + endpoints[].input + query_params: 94 required, 94 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in §2.12 ordered list, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (quotation-counter via expected_quotation_version + ERR_STALE_VERSION/412; po-amend via expected_po_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all transitions across FactoryAudit, ComplianceDocument, SourcingRequest, Sample, Quotation, PurchaseOrder, ProductionMilestone, Inspection, Shipment, QualityClaim, Factory fully expressed with from/to states, preconditions paired to error ids, and side effects, 0 missing
- calculations[]: audit_score (variant-keyed weights, critical-finding deduction, grade bands), commission (tier boundaries + inclusive lower edge, FOB/CIF base, 0.12 CIF cap, half-up at labeled steps), aql_result (lot→sample table, Ac/Re table, three-rule verdict), chargeback (per-line round-then-sum pinned, penalty tiers with boundary disambiguation, remaining_payable guard), progress_pct (sum over VERIFIED, plan-lock at exactly 100), committed_units (status-filtered, equality allowed), compliance_posture (per-category doc-type union, live-PO scoping) — all expressed as precise prose without pseudocode, 0 missing
- validations[] conditions: all matched to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives (sample cascade on SR cancel, posture→ship_blocked cascade, claim→factory suspension cascade, etc.), 0 missing
- entities[].fields[] structured content: defaults, enums, and computed derivations reconstructible from prose (e.g., Sample.revision_count default 0, Quotation.round_count 0/last_actor_role FACTORY on create, PO initial dimensions), 0 missing
- sibling-branch symmetry: parallel transition branches (SUBMITTED→APPROVED vs →REJECTED, OPEN↔COUNTERED alternation, FILED→APPROVED vs →REJECTED, etc.) receive equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 522
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Document shape**: 13 §2 subsections (RBAC with per-role identity translation, verbatim §2.2 envelope, pagination, common properties, logical clock, money/precision, OCC, capacity buckets, compliance posture ship gate, audit grading, nested retrieval, 11-step validation priority, status codes) and 10 §3 subsections organized by business lifecycle (bootstrap → audits/docs → SR+samples → quotations → PO+amend → milestones+inspections → commission calc → AQL calc → shipments → claims/cascade). §4 is the 4-column endpoint table; §5 is the 2-column error catalogue covering all 55 scaffold errors.

## Step 5: Generate Unit Tests — 2026-08-14T13:25:00.000Z

Test generation for task 1722 is complete.

## What was generated

**`test_helpers/` (Stage 1)** — 9 files under `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/test_helpers/`:
- `types.py` — 6 role enum + 21 domain status/type enums + 14 entity TypedDicts (all entities carry common fields)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (49 methods)
- `api_errors.py` — all 55 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_po_unit_conservation` and `assert_chargeback_zero_sum` invariant checkers
- `factories.py`, `constants.py` (AQL plan, tier/threshold/cap constants, required-docs map), `test_users.py` (opaque-role constants + per-entity `make_*_headers` builders for the four entity-backed roles)
- `fixtures.py` — composite setup tiers: entity creators, grade-A factory builder, compliance-doc upload/verify, `setup_po_scenario` (full chain to ACTIVE PO), `advance_to_production_complete`, `book_and_pass_psi`, `ship_and_close`, `setup_closed_po`, claim helpers

**`test_suite/` (Stage 2)** — `conftest.py` + 11 test files, **91 test functions** (93 collected items; the missing-auth test is parametrized ×3):
- test_01 bootstrap/envelope/auth/listing/clock (9), test_02 audits/compliance (9), test_03 samples/SR (8), test_04 quotation negotiation (10), test_05 purchase orders/capacity/conservation (11), test_06 milestones (7), test_07 inspection booking (8), test_08 AQL results (5), test_09 shipments (7), test_10 commission (6), test_11 quality claims/chargeback (11)

## Coverage audit results

- **Queue A (difficulty): all 18/18 instances have exactly 2 tagged tests** — verified programmatically.
- **Queue B (corner): 55/56 non-stub instances have 1 tagged test.** One instance deliberately skipped per the PRD-first filter: `Corner/endpoints/fk_reverse_reachability_filtered_lists` — the PRD never names any resource-specific filter query parameter (§2.3 specifies only `limit`/`offset`; the §4 table just says "(filtered)"), so filter semantics fail both coverage and unique derivability. Gap left as a gap, no placeholder.
- Every test docstring carries verbatim PRD citations (automated grep of all quoted spans against PRD.md: 0 misses) and ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance.
- No `skip`/`skipif`/`xfail` markers, no scaffold references in generated code, all files compile, and `pytest --collect-only` succeeds (93 items).

## Judgment calls worth noting

- **Accept returns HTTP 200**, per PRD §2.13 ("accept/counter/reject calls … return HTTP 200"), which overrides the scaffold endpoint table's 201; the only test pinning accept status asserts 200, and fixtures use the lenient `get_success_data` elsewhere.
- Priority-pair difficulty instances were kept (not silence-skipped) because PRD §2.12 explicitly enumerates the validation priority order and the masking rule verbatim.
- Two corner instances were narrowed to their PRD-derivable assertions only: `clock_endpoint_reports_default_and_new_time` (dropped the `current_utc` echo assertion — response field name is not in the PRD; kept the accept-at-default-clock proof) and `list_pagination_envelope_and_defaults` (dropped the `factory_id` filter assertions; kept envelope/defaults plus limit/offset paging).
- `immediate_visibility_of_writes` asserts mutation response + immediate GET state; the `updated_at`-inequality assertion was dropped as non-deterministic for correct millisecond-precision implementations.

## Step 6: Generate Implementation — 2026-08-14T13:25:00.000Z

Implementation complete and verified. All files live in `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/workspace/implementation/`.

## What was built

A Python + Flask REST API implementing the full import buying-agent spec (14 entities, 41 endpoints, 10 state machines, 7 calculation rules), generated purely from this task's `INSTRUCTION.md`, `SCAFFOLD.yaml`, and `PRD.md`:

- **`start.sh`** — executable; guarded dependency install (`if ! python3 -c "import flask"`) so per-test reboots skip pip; `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — app assembly, envelope-wrapped error handlers (ApiError / 404 / 405 / 500), blueprint registration.
- **`db.py`** — empty-at-boot in-memory store; logical clock defaulting to exactly `2026-08-01T00:00:00Z`, never wall-clock; all timestamps emitted ISO 8601 UTC with 3 fractional digits; `version` starts at 1, `touch()` bumps on every mutation.
- **`response.py` / `errors.py` / `middleware.py`** — scaffold-exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta, defaults 10/0, clamped 1–100); `X-User-ID`/`X-User-Role` auth with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400) → `ERR_FORBIDDEN_ROLE` (403) ordering; body/type/enum/range validation.
- **`services/domain.py`** — all calculations with `Decimal` ROUND_HALF_UP: audit score (variant-keyed weights, 2dp contributions, ONSITE critical-finding deduction floored at 0), tiered commission (provisional basis includes the new PO; final re-evaluated at close; CIF 12% cap), AQL sampling/acceptance tables, per-line-then-summed chargeback, committed-units capacity, compliance posture with ship-gate cascade, clock sweeps, PO close, factory-suspension cascade.
- **`routes/`** — one module per resource group implementing the PRD §2.12 validation priority, including the endpoint-specific PRD §3.4 orderings for counter (state → OCC → wrong-party → ownership → round cap → expiry) and accept (state → ownership → OCC → expiry → suspended → grade → MOQ → capacity), OCC via `expected_quotation_version`/`expected_po_version` (412), segregation of duties on claim adjudication, alternating counter sides, revision/round caps, half-open inspector window overlap, and zero-sum chargeback bookkeeping.

No entities are seeded at startup; the store is a module-level empty `Store()`.

## Verification

- 79-check end-to-end smoke run: all pass (bootstrap, audit scoring/approval, sample revision cap 3 → terminal REJECT on 4th request, negotiation alternation/OCC/duplicate gate, accept with MOQ/capacity, posture flip on live PO + doc verify unblock, milestones/lock/progress, DUPRO/PSI gates + AQL boundaries, shipment lifecycle through PO close, claim window + SoD + per-line chargeback, clock sweeps, pagination).
- 39-check edge run: all pass (amend OCC/`ERR_AMEND_BELOW_SHIPPED`-adjacent paths/capacity recheck, PO cancel capacity release + ytd exclusion, commission tier boundaries exactly 10,000,000→400bp and 9,999,000→500bp, CIF cap bite, shipment-cancel revert to ACTIVE, 2.1M claim → factory SUSPENDED → quotation/PO cascade, doc-expiry sweep → NON_COMPLIANT → ship_blocked, SR cancel cascade, round cap 6, SCREENING approval leaving factory grade untouched).
- Harness contract: `bash start.sh` from `implementation/` boots in ~2s, twice consecutively, with an empty store on the second boot (unknown buyer → `ERR_BUYER_NOT_FOUND`, list totals 0), confirming clean per-test-server restarts.

## Step 7: Run Tests and Iterate — 2026-08-14T13:40:00.000Z

All 8 parallel rounds pass 93/93 — exit condition met.

## Summary

**Iterations run:** 2 (round 1 sweep: 86/93 in all 8 rounds, identical deterministic failures; round 2 sweep after fixes: 93/93 × 8 rounds).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all fixes were faithfulness fixes, no deletions, no weakened assertions.

**Fixes applied to test artifacts (test_suite/):**

1. `test_suite/test_04_quotation_negotiation.py` — `_two_factory_grade_scenario`: inserted `set_clock("2026-08-02T00:00:00Z")` between the first audit approvals and the downgrade audit approval. The scenario relies on PRD §2.10's "most recent `approved_at`" selection, but with the frozen logical clock both audits tied on `approved_at` AND `created_at`, exhausting the PRD tie-break chain and leaving the outcome dependent on an unspecified implementation-level tie-break. Advancing the clock makes the downgrade uniquely "most recent" under every PRD-faithful reading. (Failure: `test_accept_rejected_when_factory_grade_c`.)
2. `test_suite/test_07_inspection_booking.py` — `_ship_blocked_with_overlapping_inspector(self, api, advance_clock)`: the helper referenced the `api` fixture as a bare name outside its scope (`NameError`); added the parameter and passed `api` at both call sites. (Failures: both `TestSafetyBeatsOverlapPriority` tests.)
3. `test_suite/test_07_inspection_booking.py` — `_po_production_complete()`: added `with_inspector=True`; both `TestResultRecording` tests use `ctx["inspector"]["id"]` which was never created (`KeyError`).
4. `test_suite/test_08_aql_results.py` — `_po_complete()`: added `with_inspector=True`; `test_error_aql_sample_mismatch_trigger` uses `ctx["inspector"]["id"]` (`KeyError`).

**Fixes applied to implementation/:**

1. `workspace/implementation/routes/quotations.py` — `accept_quotation`: return HTTP 200 instead of 201. PRD §2.13 verbatim: "Modifications of an existing resource — including all state transitions, accept/counter/reject calls, verifications, reviews, and sweeps — return HTTP 200." (Failure: `test_po_total_and_remaining_payable_computed`.)
2. `workspace/implementation/routes/inspections.py` — `book_inspection`: moved the DUPRO/PSI production-readiness gates (§2.12 priority 8) ahead of the inspector window-overlap check (priority 9) to match PRD §2.12's strict evaluation order. Latent violation, not pinned by any current test; zero risk to the suite.

No tests failed STEP 1 coverage/unique-derivability audit; the grade-C test was kept and made determinate rather than deleted, since PRD §2.10 covers the rule and only the frozen-clock setup made it non-derivable.

## Step 8: Finalize PRD — 2026-08-14T13:48:00.000Z

Done. PRD_FINALIZED.md written with exactly two inline edits; both trace to step_7_diff items and survived the no-new-mismatch check.

**Line counts / delta:** PRD.md 381 lines, PRD_FINALIZED.md 381 lines — 0% line-count delta; 2 of 381 lines modified (~0.5%), both in-place inline edits, no new sections.

**Changes:**
- §2.10 — revise — extended the approved-onsite-audit tie-break chain with a terminal clause: audits still tied on both `approved_at` and `created_at` are ordered by creation order, earliest-created first — `implementation/services/domain.py:114-121` (sort key `-_approved_dt, +_created_dt, +_seq, -_approved_seq`; `_seq` ascending is the effective terminal key since it is unique, making the fourth key unreachable).
- §3.6 — revise — reordered the inspection-booking gate enumeration so DUPRO/PSI production-readiness checks (§2.12 priority 8) precede the inspector window-overlap check (priority 9), matching the "in §2.12 order" lead-in and the implementation — `implementation/routes/inspections.py:90-107`.

**Items needing no edit (verified, not assumed):**
- Impl fix #1 (accept returns 200): PRD §2.13 already pins verbatim "accept/counter/reject calls … return HTTP 200"; the implementation was aligned to the PRD, not vice versa.
- Test fixes #2–#4 (bare-name `NameError`, missing `with_inspector=True`): pure test-fixture bugs, no behavioral content.

**Per-edit pre-edit search log:**

Edit 1 (§2.10 tie-break):
- (a) Subject: selection of the winning approved ONSITE audit that rewrites `factory.latest_audit_grade`/`audit_score`.
- (b) Enumerated impl paths: `services/domain.py:98-132` `refresh_factory_grade` (sole selection site — full re-derivation over all approved onsite audits); `routes/audits.py:83-98` `approve_audit` (sole caller, refreshes on every ONSITE approval); `routes/registry.py:124-126` (initial `NONE`/0 values — read/initialized, not selected); `routes/quotations.py:86,254` (read-only grade gate for quotation create/accept). Grep for `refresh_factory_grade|latest_audit_grade|audit_score|_grade_source|_approved_seq|_approved_dt` across all `*.py` confirmed no other selection or read site.
- (c) Wording adjustment: phrased as "creation order, earliest-created first" (an observable request-order notion) instead of naming the internal `_seq` counter, and deliberately stopped before the unreachable fourth sort key (`-_approved_seq`) to stay under-determined; appended as an extension of the existing chain rather than a replacement, so all enumerated read/gate paths remain accurately described.

Edit 2 (§3.6 booking-gate order):
- (a) Subject: evaluation order of inspection-booking validation gates.
- (b) Enumerated impl paths: `routes/inspections.py:50-127` `book_inspection` (sole booking endpoint; post-fix order: PO ACTIVE → factory ACTIVE → `ship_blocked` → DUPRO readiness → PSI readiness → window overlap); `routes/inspections.py:33-47` `_window_overlaps` (only `BOOKED` inspections block); `routes/shipments.py:63-68` reuses `ERR_PO_NOT_READY_FOR_PSI` for shipment booking — governed by §3.9's separate sentence, untouched by this edit. Grep for `ERR_PO_NOT_READY_FOR_DUPRO|ERR_PO_NOT_READY_FOR_PSI|ERR_INSPECTION_WINDOW_CONFLICT|_window_overlaps` confirmed no other call sites.
- (c) Wording adjustment: pure clause reordering within the existing sentence (readiness clauses moved before the overlap clause, joined with "and"); no semantic narrowing or widening, and the pre-existing "(or otherwise live)" parenthetical was left as-is since it is out of scope for this fix.

## Step 9: Complete PRD — 2026-08-14T14:12:00.000Z

All edits are in. The file went from 381 to 385 lines. Here is the summary.

## Summary

**Files**: `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/workspace/PRD_FINALIZED.md` (381 lines / 51,624 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1722_import_sourcing_buying_agent_services/workspace/PRD_COMPLETED.md` (385 lines / 58,521 chars; +4 lines, +6,897 chars). 24 inline edits; no new sections, no invented behavior.

**Counts**: ambiguity-pins ≈ 24, mismatch-revisions = 6.

**Changes** (impl paths relative to `workspace/implementation/`):

- §2.2 — revise — ambiguity — error envelope now covers 4xx and 5xx; added fallback sentence: unrouted path → `ERR_NOT_FOUND` 404, wrong method → `ERR_VALIDATION` 405, unhandled → `ERR_INTERNAL` 500 — app.py:51-66
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values are clamped (1/100/0), non-integer → `ERR_VALIDATION` 400 — middleware.py:114-134
- §2.3 — revise — ambiguity — list sort ties on `created_at` break by creation order — middleware.py:137-139
- §2.4 — insert — ambiguity — all server timestamps (`updated_at`, `approved_at`, `delivered_at`, `api_request_timestamp`) stamp from the logical clock — db.py:53-55,90-104
- §2.5 — revise — ambiguity — clock endpoint: missing/unparseable `to_iso8601` → `ERR_VALIDATION` 400; responds `{"current_utc": "<string as supplied>"}`; any parseable instant accepted (backward sets allowed) — routes/clock_routes.py:14-31
- §2.6 — insert — ambiguity — `Agent.commission_ytd_cents` = sum of `final_commission_cents` over the agent's `CLOSED` POs whose `created_at` year equals the clock year — services/domain.py:55-66
- §2.7 — insert — ambiguity — missing/non-integer expected-version field → `ERR_VALIDATION` 400 (not `ERR_STALE_VERSION`) — routes/quotations.py:39-56, routes/purchase_orders.py:81-89
- §2.8 — insert — ambiguity — amendment capacity variant: PO excluded from committed sum, candidate = amended `ordered_qty` − `cancelled_qty` — routes/purchase_orders.py:129-143, services/domain.py:207-217
- §2.12 — revise — **mismatch** — swapped buckets 3/4: path existence is checked before ownership scoping (impl does 404-before-403 universally) — e.g. routes/sourcing_requests.py:87-95, routes/quotations.py:156-157,184-198
- §2.12 item 5 — revise — **mismatch** — removed `ERR_WRONG_COUNTER_PARTY`/`ERR_NEGOTIATION_ROUND_EXCEEDED` from the state bucket (they fire after OCC on counter) — routes/quotations.py:171-204
- §2.12 item 8 — revise — ambiguity — grade gate applies to quotation creation and acceptance — routes/quotations.py:86-91,254-259
- §2.12 closing — insert — ambiguity — body-schema validation placement (before buckets, except OCC fields at bucket 6 and the PO-amend change-set after the state check); required string fields accept empty strings; §3 endpoint-specific orders govern — routes/purchase_orders.py:75-119
- §3.1 — revise — **mismatch** — `country_code` is an opaque string, no ISO alpha-2 format validation — routes/registry.py:36-37 (middleware.py:54-60 `req_str`)
- §3.2 — insert — ambiguity — audits creatable in any factory status, unlimited concurrent `SUBMITTED`; `critical_findings` must be a non-negative integer — routes/audits.py:26-37
- §3.2 — revise — ambiguity — `issued_date` opaque string; `expires_at` must parse as ISO 8601 (not required in the future); upload does not recompute posture — routes/documents.py:30-48
- §3.3 — revise — ambiguity — `assigned_agent_id` not resolved against registry; `target_price_cents` any integer — routes/sourcing_requests.py:39-44
- §3.3 — insert — ambiguity — sample creation requires SR `OPEN`/`IN_PROGRESS` (`ERR_SR_NOT_ACTIVE`) — routes/sourcing_requests.py:137-140
- §3.3 — revise — ambiguity — review `comments` accepted but never persisted — routes/sourcing_requests.py:185
- §3.3 — insert — ambiguity — resubmit has no SR-status gate — routes/sourcing_requests.py:212-233
- §3.4 — insert — ambiguity — quotation numeric fields unconstrained; `valid_until` parse-checked but not clock-checked at creation; creation requires SR active (`ERR_SR_NOT_ACTIVE`) and caller resolvable to a Factory (`ERR_FACTORY_NOT_FOUND`) — routes/quotations.py:66-83
- §3.4 — revise — **mismatch** — counter preconditions "evaluated in the §2.12 order" → "in this order" (the §2.12 numbering does not match counter's actual sequence) — routes/quotations.py:170-208
- §3.4 — insert — ambiguity — counter expiry check uses the pre-update `valid_until`; wrong-party precedes ownership — routes/quotations.py:176-214
- §3.4 — revise — ambiguity — `delivery_month` month 01–12; `freight_cents`/`insurance_cents` accepted/stored for either `commission_mode` — middleware.py:19,105-111, routes/quotations.py:226-228
- §3.4 — insert — ambiguity — accept returns the created `PurchaseOrder` with HTTP 200 (not the quotation, not 201) — routes/quotations.py:319-321
- §3.5 — revise — ambiguity — amend change-set is type-validated only (below-shipped floor aside); successful amend also recomputes `commission_rate_bp` and `remaining_payable_cents` — routes/purchase_orders.py:96-156
- §3.6 — revise — ambiguity — milestone verify requires PO `ACTIVE` (`ERR_PO_NOT_ACTIVE`), reject has no PO-state gate, both use `ERR_MILESTONE_NOT_VERIFIABLE` — routes/milestones.py:88-136
- §3.6 — revise — ambiguity — booking: `inspector_id` any non-empty string (no registry resolution), any valid `scheduled_date`, `lot_size` ≥ 1, window conflict counts only `BOOKED` inspections; new inspection has null defect counts and `result` `NONE` — routes/inspections.py:33-70,108-127
- §3.6 — revise — ambiguity — defect counts each non-negative integers (`ERR_VALIDATION`) — routes/inspections.py:159-161
- §3.6 — revise — **mismatch** — `latest_psi_result` reflects the most recently recorded PSI (last record wins), replacing the updated_at/created_at tie-break rule — routes/inspections.py:189-193
- §3.9 — revise — **mismatch** — "three readiness gates" (which listed four) now names the PO-state gate (`ACTIVE`/`PARTIALLY_SHIPPED`, else `ERR_PO_NOT_ACTIVE`) plus the four gates — routes/shipments.py:48-74
- §3.9 — revise — ambiguity — handover: non-`BOOKED` → `ERR_SHIPMENT_STATE_INVALID`; `doc_refs` elements must be strings — routes/shipments.py:130-149
- §3.9 — revise — ambiguity — close stores `final_commission_cents` and re-stores `commission_rate_bp`; commission feeds the §2.6 roll-up — services/domain.py:316-332
- §3.9 — revise — ambiguity — shipment cancel: non-`BOOKED` → `ERR_SHIPMENT_STATE_INVALID`; PO status recomputed (`ACTIVE` if no live shipments, else `PARTIALLY_SHIPPED` if `open_qty` > 0, else `SHIPPED`) — routes/shipments.py:193-209
- §3.10 — revise — ambiguity — `items` non-empty, `description` a required string; claim carries `defect_rate` (JSON number, 4-dp half-up) computed at filing and recomputed at approval against then-current `ordered_qty` — routes/claims.py:34-66,90-103,159-171
- §4 — revise — ambiguity — pinned the exact-match filter query params per list endpoint; unknown params ignored — routes/*.py list handlers (e.g. routes/purchase_orders.py:40-52)
- §5 — insert — ambiguity — added catalogue rows `ERR_NOT_FOUND` 404 and `ERR_INTERNAL` 500 — app.py:51-66

**Key finding**: the only substantive contradictions were the §2.12 global validation order (impl resolves path existence before ownership everywhere, and evaluates OCC before counter-party/ownership on quotation counter), the unpersisted `country_code` format claim, the `latest_psi_result` tie-break rule, and §3.9's gate miscount; everything else was PRD silence pinned to impl behavior.
