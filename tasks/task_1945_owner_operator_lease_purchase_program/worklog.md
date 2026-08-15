# Worklog — task_1945_owner_operator_lease_purchase_program

## Step 1: Create Task Directory — 2026-08-15T02:17:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1945_owner_operator_lease_purchase_program/` and `workspace/` verified present. No new index computed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-15T03:12:00.000Z

Orchestrator note: the subagent's first pass wrote files in chunks via append, producing YAML syntax errors (unquoted `name?` tokens and `$.data[0].id` / `errors[ERR_X]` tokens inside flow sequences). Orchestrator repaired all three files with a quoting pass (no content changes); all parse clean. Corner design initially covered only the `entities` section (7 instances); orchestrator resumed the same subagent to complete the §1.9 breadth walk across the remaining eight sections. Final verification: name uniqueness holds across both design files (19 + 53 = 72 names); all three files parse; sections present: entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model.

Subagent summary (verbatim):

All done. Final state is clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1945_owner_operator_lease_purchase_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Scaffold contents (queue source):**
- Entities: 10 (OwnerOperator, Truck, LeaseAgreement, EscrowAccount, SettlementStatement, LaneAssignment, ServiceBay, MaintenanceWorkOrder, ComplianceDocument, BuyoutQuote) — flat topology, FK-linked
- State machines: 9, with explicit cycles (LeaseAgreement ACTIVE↔DEFAULTED, SettlementStatement ISSUED↔DISPUTED, Truck relist loop AVAILABLE→…→AVAILABLE, doc-driven classification PENDING_REVIEW/VERIFIED/FLAGGED)
- Calculations: 9 (provisional-vs-final settlement waterfall, buyout scheduled-vs-early pricing with pinned evaluation order, guarantee top-up, escrow credit/cap, per-line rounding order, warranty billing determination, missed-payment tracking, lane half-open overlap, bay 2-hour buffer)
- Validations: 9 priority tiers (auth → existence → state → safety → temporal → constraint → referential → fiscal)
- Endpoints: 48 (incl. `POST /lease-program/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default)
- Error catalog: 46
- Roles: 5 (Driver is `entity_backed:OwnerOperator`; 4 opaque carrier roles); 1 OCC concurrency rule (buyout quote create on LeaseAgreement.version → ERR_STALE_VERSION/412)

**Difficulty design (queue A): 19 instances** — 2+ per rule × 9 rules (rule 2 carries 3, one per mode a/b/c). All formula-derived asserts pre-computed as literals (e.g., EARLY quote 4831500, final-basis net 28000, rounding-order 46480-not-46479).

**Corner design (queue B): 46 active instances + 7 `excluded_because` stubs (53 entries)**, across all 9 guide sections: entities 7, state_machines 16, calculations 3 (+4 stubs), validations 8 (+2 stubs), endpoints 3, errors 1 (six 404 families), rbac 4, cross_cutting_layers 3 (OCC stale/fresh, classification recompute), consistency_model 0 (+1 stub). All stub refs resolve to §1.8 instance names; names unique across both files.

**Verification:** all three files parse; no forbidden concurrency vocabulary; every error id is triggered by at least one instance; `scaffold_lint.py` verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(827 calls scanned; the one initial violation — missing `GET /service-bays/{id}` — was fixed by adding the endpoint to §1.5.)

## Step 3: Copy Shared Files — 2026-08-15T03:13:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1945_owner_operator_lease_purchase_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T03:18:00.000Z

PRD generation complete. The document was written to `/home/ubuntu/github/CodingPRD/tasks/task_1945_owner_operator_lease_purchase_program/workspace/PRD.md`. The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1945_owner_operator_lease_purchase_program/workspace/PRD.md` — 280 lines.

**Section list:**
- §1 Introduction (2 paragraphs: business context + system commitments)
- §2 Global Specifications (9 subsections): 2.1 RBAC (5 roles, identity semantics for opaque vs entity-backed `Driver`), 2.2 Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending, 4 meta fields), 2.4 Common Resource Properties (UUID id, ISO 8601 timestamps, version semantics, unknown-field tolerance), 2.5 The Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.6 Monetary Precision (integer cents, per-line round-half-up before summation), 2.7 OCC (`expected_lease_version` → `ERR_STALE_VERSION`/412, single-endpoint scope), 2.8 Validation Ordering (all 9 priority tiers), 2.9 Resource Topology (flat graph, reverse-lookup filters)
- §3 Business Logic (8 subsections organized by workflow stage): onboarding/truck lifecycle, compliance documents + classification recompute, lease creation/activation, weekly settlement dual-basis waterfall, revenue guarantee + lanes, maintenance + warranty attribution, default/cure/termination/completion, buyout pricing/acceptance
- §4 Endpoint Definitions: 48 endpoints, 4-column table
- §5 Error Code Catalogue: 46 error IDs, 2-column table

**Coverage self-audit (all three hard contracts PASS, verified by scripted diff against the scaffold):**

```
Field coverage check:
- entities[].fields + endpoint inputs + common fields: 78 required, 78 present, 0 missing
- Status: PASS

Rule coverage check:
- validations[] priority ordering: 9 tiers expressed in order (§2.8)
- concurrency_rules[]: 1/1 (buyout-quote create: endpoint + expected_lease_version + ERR_STALE_VERSION/412 all named, no race framing)
- state_machines[].transitions: all 10 machines, every from→to pair with preconditions + side_effects expressed (incl. terminate APPLICATION-variant cascade, finalize 3-link escrow cascade, default 2-link guarantee-strip cascade)
- calculations[]: 9/9 in precise prose (rounding order pinned, waterfall step order, guarantee boundary ==0, cap >= boundary, buyout 4-step order, inclusive warranty boundaries, >=3 default threshold, 2h bay-gap boundary, half-open lane adjacency)
- validations[] conditions: every error_id matchable to its trigger in §2/§3 prose
- endpoints[].side_effects: all 48 narrated
- field structured content: defaults/initials/enums reconstructible (PENDING_REVIEW, zero counters, escrow_satisfied false, quote TTL 7d, 12.5¢/mile, 50000 floor, 0.10 early rate, required doc set excludes MEDICAL_CARD)
- sibling-branch symmetry: terminate 3 variants, buyout SCHEDULED/EARLY, settlement provisional/final bases, RECALL/PREVENTIVE/REPAIR all equal density
- Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 421
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
- Status: PASS

Auxiliary: 46/46 error IDs present; all state values present; all enum values present; 48/48 endpoint paths in §4; 5/5 role names present.
```

## Step 5: Generate Unit Tests — 2026-08-15T03:35:00.000Z

Generation complete and fully audited. Summary:

## Test counts

**Queue A (Difficulty) — 38 tests** across all 19 instances (exactly 2 each):
- `dual_variant_calc`: settlement_maintenance_provisional_vs_final, buyout_price_scheduled_vs_early
- `combinatorial_formula`: waterfall_nested_min_max_guarantee_escrow_lease, per_line_rounding_order_pinned, buyout_evaluation_order_pinned
- `non_linear_state_machine`: lease_default_cure_cycle, settlement_dispute_reissue_cycle
- `transitive_cascade`: finalize_escrow_full_cascade_sets_lease_flag, declare_default_revokes_lane_strips_guarantee
- `priority_pair_validation_conflict`: activate_state_error_beats_compliance_error, lane_overlap_error_beats_commitment_floor
- `boundary_precision_check`: escrow_cap_exact_cent_reach, guarantee_exact_gross_boundary
- `cross_entity_state_dependency`: activation_requires_operator_verified, issue_requires_lease_active_or_defaulted
- `resource_temporal_overlap`: lane_half_open_adjacency_vs_overlap, bay_two_hour_buffer_semantics
- `compensating_invariant`: escrow_credit_refund_conservation, settlement_funds_conservation_across_reissue

**Queue B (Corner) — 44 tests** across all 44 translatable non-stub instances (exactly 1 each): 5 entities + 16 state_machines + 3 calculations + 9 validations + 3 endpoints + 1 errors + 4 rbac + 3 cross_cutting_layers.

**Total: 82 tests**, all collected cleanly by pytest.

## Instances skipped (2, both queue B)

1. `Corner/entities/owner_operator_create_missing_cdl_returns_invalid_request` — `ERR_INVALID_REQUEST` appears only in the PRD §5 status table; no PRD prose states a trigger for omitting a required field, so the asserted error_id fails PRD coverage (two readers could ship different error ids).
2. `Corner/entities/compliance_doc_invalid_enum_returns_invalid_request` — same: no PRD prose names `ERR_INVALID_REQUEST` for an out-of-enum `doc_type`. Verified by grep: the id occurs only at PRD.md:238 (the §5 table).

The 7 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references resolve to real queue-A instances.

One adjustment made during translation: `waterfall_nested_min_max_guarantee_escrow_lease`'s `payment_short_flag == true` assertion targets the create (DRAFT) response, but PRD §3.4 pins the flag to finalize time — so the second test for that instance asserts the flag at FINALIZE (final-basis recompute: lease applied 38000, shortfall 27000), which is the uniquely derivable moment.

## Files

`test_helpers/` (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1945_owner_operator_lease_purchase_program/test_helpers/`): `__init__.py` (barrel), `types.py` (10 TypedDicts + 12 enums, all entities carry common fields), `api_client.py` (48 endpoint methods under `/lease-program`), `api_errors.py` (45 error ids, registered via `set_error_http_status_map`), `assertions.py` (per-entity + escrow/settlement conservation invariants), `factories.py`, `constants.py` (12.5 cpm reserve, 50000 lane floor, 2h bay buffer, default threshold 3, 0.10 early fee, 7-day quote TTL, standard 52-week terms), `test_users.py` (4 opaque role headers + `make_driver_headers` for entity-backed Driver), `fixtures.py` (composite setups: verified operator, active lease, healthy/short finalized weeks, missed-payment/defaulted leases, lane accept, work-order complete, OCC-fresh buyout quotes).

`test_suite/` (11 files, under `.../test_suite/`): `conftest.py` + `test_01_onboarding_and_compliance.py` … `test_10_rbac_and_ownership.py`.

## Audit results

- Tag coverage: every non-stub instance in §1.8 has ≥2 tests, every non-stub instance in §1.9 has exactly 1, each tagged with a docstring-final `Design: …` line copied verbatim from the yaml `name:` — programmatically verified (CLEAN).
- PRD citations: all 115 quoted docstring segments verbatim-match PRD.md after whitespace normalization (CLEAN).
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated comments/docstrings; pyflakes clean; 82 tests collect without a server.

## Step 6: Generate Implementation — 2026-08-15T03:35:00.000Z

Confirmed: `bash start.sh` boots in the foreground (via `exec python3 app.py`), binds `0.0.0.0:$PORT` (default 10000), and serves HTTP within seconds. Implementation is complete.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1945_owner_operator_lease_purchase_program/workspace/implementation/`):

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 68 |
| `db.py` | 21 |
| `errors.py` | 67 |
| `response.py` | 51 |
| `clock.py` | 24 |
| `middleware.py` | 46 |
| `util.py` | 166 |
| `routes/__init__.py` | 0 |
| `routes/operators.py` | 45 |
| `routes/trucks.py` | 79 |
| `routes/leases.py` | 287 |
| `routes/settlements.py` | 197 |
| `routes/escrow.py` | 50 |
| `routes/lanes.py` | 130 |
| `routes/maintenance.py` | 196 |
| `routes/compliance.py` | 111 |
| `routes/buyout.py` | 188 |
| `routes/clock_routes.py` | 19 |
| `services/__init__.py` | 0 |
| `services/core.py` | 185 |
| `services/serialize.py` | 174 |
| **Total** | **2115** |

**Endpoints implemented: 41** — the complete §1.5 endpoint table (10 entity resource groups covering all CRUD, state-transition actions, and the `POST /lease-program/_clock/set_current_utc` test-driving clock).

**Key behaviors verified by an end-to-end smoke suite (all 47 checks passed on a fresh boot):** full waterfall arithmetic with per-line round-half-up, provisional vs final maintenance basis, guarantee eligibility/top-up, escrow credit → FULL flip → `escrow_satisfied` latch (equality triggers), missed-payment/arrears accumulation, declare-default cascade (lane revoke + guarantee-strip recompute of non-final settlements), cure with cap-respecting overpayment-to-escrow, terminate cascade (escrow arrears application → REFUND_PENDING/CLOSED, settlement cancel, lane revoke), completion with escrow disburse, buyout OCC (`ERR_STALE_VERSION` 412), SCHEDULED/EARLY pricing with pinned 4-step evaluation, quote supersede, quote expiry 409, lazy doc expiry → FLAGGED recompute on read, bay 2-hour buffer (exactly-2h allowed), lane half-open overlap (adjacency allowed), truck odometer monotonic raise, envelope/pagination shape, and auth/RBAC/ownership errors.

**PRD-vs-scaffold ambiguities resolved:**
- *Validation tier ordering on multi-failure requests* — PRD §2.8's narrative order (auth → ownership → existence → state → business) was applied per-endpoint (e.g., settlement state check before lease-state check, matching the PRD's "issuing a non-draft fails with ERR_SETTLEMENT_NOT_DRAFT" pairing).
- *Reissue guarantee eligibility* — PRD says reissue recomputes "under the provisional basis"; I keep the guarantee stripped when the lease is DEFAULTED (consistent with the declare-default cascade's forced-zero recompute), rather than re-deriving eligibility that a DEFAULTED lease always fails anyway (`status == ACTIVE` required) — the force-zero flag is equivalent but explicit.
- *Escrow FULL flip on cure-overpayment* — scaffold defines FULL only via settlement-finalize trigger; cure overpayment credits the balance but does not flip ACCUMULATING→FULL (PRD §3.7 names only balance/total_credited changes), so no flip on cure.
- *Quote expiry check ordering* — on accept, `ERR_QUOTE_NOT_GENERATED` (state, tier 4) is checked before `ERR_QUOTE_EXPIRED` (temporal, tier 6) per PRD §2.8 priority.
- *Timestamps* — entity `created_at`/`updated_at` use wall-clock UTC with 3 fractional digits per PRD §2.4; only temporal *business rules* read the logical clock (PRD §2.5).

**Boot contract confirmed:** `bash start.sh` from `./implementation/` runs the server in the foreground via `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), guards `pip install` behind a flask-import check, seeds nothing (store starts empty; verified by repeated fresh-boot smoke runs), and answered HTTP 200 within ~4 seconds of invocation.

Orchestrator note: endpoint reconciliation after Steps 5+6 — subagent reported "41 endpoints" but an automated diff of Flask blueprint routes against SCAFFOLD.yaml §1.5 shows all 48 scaffold endpoints (method+path) are present, zero missing, zero extra.

## Step 7: Run Tests and Iterate — 2026-08-15T03:58:00.000Z

All 8 rounds pass 82/82. Clean sweep achieved — exiting with the summary.

---

## Summary

**Iterations run:** 3 (eight parallel rounds each; final sweep: 82/82 passed in every round).

**Tests deleted:** None. Both semantic failures traced to verbatim PRD rules with uniquely determined outcomes, so no deletion was warranted.

**Fixes applied to `test_suite/`:**
- `test_04_settlement_lifecycle.py::test_settlement_funds_conservation_across_reissue` — corrected the hardcoded expected `net_pay_cents` from 62500 to 63000. PRD §3.4's waterfall with a 10000-cent maintenance override yields 250000 − 70000 (fuel) − 22000 (insurance) − 10000 (maintenance) − 20000 (escrow) − 65000 (lease payment) = 63000; the old value was a mis-derived constant that even violated the test's own funds-conservation assertion (249500 ≠ 250000).

**Fixes applied to `test_helpers/`:**
- `api_client.py` — `ApiClient.__init__` now sets `Connection: close` as a session default header. Under per-test-server isolation the harness SIGKILLs and respawns the server before every test, and the module-level `requests.Session` was pooling keep-alive connections to the dead server process; reuse surfaced nondeterministically as `RemoteDisconnected` / `ConnectionResetError(104)` mid-setup (this produced the rounds 5–7-only flake in `test_activate_state_error_not_compliance_error_when_both_fail` in sweep 2). Transport hygiene only — no semantic change to any assertion.

**Fixes applied to `implementation/`:**
- `services/core.py::recompute_classification` — per required doc type, a VERIFIED unexpired document now satisfies the type even when an older REJECTED/EXPIRED document of the same type is on file (previously any historical REJECTED doc pinned the operator at FLAGGED forever). This implements PRD §3.2 verbatim: "A `FLAGGED` operator returns to `VERIFIED` only when a replacement required document is verified and unexpired, restoring the full required set." Fixed `test_doc_reject_flips_operator_flagged_then_reverify_recovers`.

**Flakiness note:** sweep 2's single failing test was purely the keep-alive transport race described above — no PRD-semantic bug — and the `test_helpers/api_client.py` fix eliminated it (sweep 3: 8/8 clean rounds, 0 failures in the union).

Orchestrator verification: re-read all 8 `results.{i}.json` after the subagent exited — every round reports passed 82/82.

## Step 8: Finalize PRD — 2026-08-15T04:04:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1945_owner_operator_lease_purchase_program/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md 280 lines, PRD_FINALIZED.md 280 lines — 0% line-count delta; 2 of 280 lines (both single-paragraph lines in §3.2) revised in place.

**Step 7 diff disposition:**
- Settlement test arithmetic fix (62500 → 63000): verified against impl `run_waterfall` (`services/core.py:128-189`) and PRD §3.4's five-step waterfall — PRD already uniquely determines 63000 (250000 − 70000 fuel − 22000 insurance − 10000 override − 20000 escrow − 65000 lease payment). **No PRD edit.**
- `api_client.py` `Connection: close` header: transport hygiene, zero API semantics. **No PRD edit.**
- `recompute_classification` fix: genuine PRD ambiguity — §3.2's "When any required document is `REJECTED`... the operator is `FLAGGED`" did not specify how a required type is satisfied when multiple documents of that type exist in different statuses, and was in tension with §3.2's own "replacement... restoring the full required set" sentence. **Two PRD edits.**

**Changes (one bullet each):**
- §3.2 (classification paragraph) — revise — pins per-type evaluation: a required type is satisfied by at least one VERIFIED doc of that type with `expires_on` strictly after the logical clock, and a satisfied type stands regardless of older REJECTED/expired docs of the same type; FLAGGED now requires the type to be unsatisfied AND have a REJECTED doc or a VERIFIED doc past expiry — `implementation/services/core.py:78-96`
- §3.2 (expiry paragraph) — revise — qualifies "dropping a `VERIFIED` operator to `FLAGGED`" with "when the expiry breaks the full required set", so the sentence stays true when a second VERIFIED-unexpired doc of the same type keeps the operator VERIFIED — `implementation/services/core.py:51-57,85-89`

**Per-edit pre-edit search log:**

Edit 1 (§3.2 classification paragraph):
- (a) Subject: derivation of `classification_status` from an operator's compliance documents when multiple documents of the same required type exist in differing statuses.
- (b) Paths enumerated and read/grepped: `services/core.py:60-101` (`recompute_classification` — per-type satisfy/flag, global flagged→FLAGGED / all-satisfied→VERIFIED / else PENDING_REVIEW), `services/core.py:51-57` (`evaluate_doc_expiry` — only VERIFIED docs flip to EXPIRED), `routes/compliance.py:25-45` (create, no recompute — matches "After any verify or reject"), `routes/compliance.py:48-80` (list/get lazy expiry + recompute on flip), `routes/compliance.py:83-111` (verify/reject + recompute), `routes/operators.py:37-45` (operator GET recompute), `routes/leases.py:132-135` (activation gate recompute requiring VERIFIED), `services/serialize.py:11` (pass-through). All classification decisions funnel through the single `recompute_classification`, so the per-type wording covers every callsite; MEDICAL_CARD stays outside the loop, consistent with the untouched "not part of the required set" clause.
- (c) Adjustment: the FLAGGED sentence was given the "required type is not satisfied" precondition (impl flags only when the type lacks a VERIFIED-unexpired doc), and the VERIFIED sentence was restated as "every required type is satisfied" to compose with the new per-type definition; "Anything in between..." and the version-increment sentence kept verbatim.

Edit 2 (§3.2 expiry paragraph):
- (a) Subject: same — classification recompute, specifically the consequence of a lazy VERIFIED→EXPIRED flip.
- (b) Same enumerated paths as Edit 1, plus re-verified `core.py:85-89` (a type with both an expired doc and a VERIFIED-unexpired doc is satisfied, no flag) — the unqualified "dropping a `VERIFIED` operator to `FLAGGED`" would have mis-described that path.
- (c) Adjustment: appended "when the expiry breaks the full required set" — the minimal qualifier that keeps the sentence consistent with the redundant-VERIFIED-doc path without rewording anything else.

## Step 9: Complete PRD — 2026-08-15T04:16:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1945_owner_operator_lease_purchase_program/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then edited in place).

**Size**: PRD_FINALIZED.md 280 lines / 42,429 chars → PRD_COMPLETED.md 280 lines / 45,194 chars (char-delta **+2,765**; 13 paragraphs touched, no sections added).

**Counts**: 10 ambiguity-pins, 3 mismatch-revisions (13 changes total).

**Changes** (section — insert/revise — kind — what — impl evidence):

- §2.2 — insert — ambiguity — Undefined paths, unsupported methods, and internal failures return the standard error envelope with `ERR_INVALID_REQUEST` at HTTP 404/405/500 — `implementation/app.py:32-48`.
- §2.3 — insert — ambiguity — Invalid `limit` (non-integer, <1, >100) or `offset` (non-integer, <0) rejected with `ERR_INVALID_REQUEST` (400); list sort ties broken by `id` ascending — `implementation/util.py:132-166`.
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are wall-clock stamps; the logical clock governs only temporal comparisons — `implementation/services/core.py:26-33,37-39`, `implementation/util.py:45-48`.
- §2.4 — insert — ambiguity — Business date/datetime fields accept ISO date or datetime (date-only → midnight UTC, offsets honored) and are echoed normalized to `YYYY-MM-DDTHH:MM:SSZ`; same form for the clock endpoint's `current_utc` — `implementation/util.py:10-42`, `implementation/services/serialize.py` (all `fmt_dt` uses), `implementation/routes/clock_routes.py:13-19`.
- §2.8 — revise — **mismatch** — Removed `ERR_RESOURCE_NOT_OWNED` from the tier-2 header group: impl evaluates Driver ownership only after the target resource's existence and its own state precondition pass (plus quote-expiry on buyout accept), before dependent-lease state checks — `implementation/routes/settlements.py:130-133`, `implementation/routes/lanes.py:79-84,113-116`, `implementation/routes/buyout.py:137-144,182-185`.
- §2.8 — insert — ambiguity — Field-level malformed input (missing/wrong-type field, non-object body, unparseable date, out-of-enum value, bad pagination) → `ERR_INVALID_REQUEST` (400) at parse time, after header/role checks, before existence lookups — `implementation/util.py:53-127` and every route body's parse-before-lookup order.
- §2.8 — insert — ambiguity — `ERR_INVALID_DATE_RANGE` window-shape checks sit immediately after existence checks and before state preconditions (not in the temporal tier) — `implementation/routes/lanes.py:34-37`, `implementation/routes/maintenance.py:71-85`.
- §2.9 — revise — ambiguity — Replaced vague "several other listings accept a `status` filter" with the exact set (settlement, lane, work-order, compliance-document, buyout-quote listings; escrow listing does not) — `implementation/routes/escrow.py:16-26` vs `leases.py:100-116`, `settlements.py:90-103`, `lanes.py:53-66`, `maintenance.py:123-139`, `compliance.py:48-69`, `buyout.py:111-124`.
- §3.4 — revise — **mismatch** — Dropped "a Monday" from `week_start_date`; impl enforces no day-of-week constraint, accepting any ISO date/datetime — `implementation/routes/settlements.py:35` (`req_dt` only).
- §3.4 — revise — **mismatch** — `payment_short_flag` is not "computed at finalize time"; it is recomputed on every waterfall run (draft create, reissue, default cascade, finalize) — `implementation/services/core.py:189` plus call sites `routes/settlements.py:85,155-157,175-176`, `routes/leases.py:169-173`.
- §3.4 — revise — ambiguity — Reissue *requires* `maintenance_deduction_override_cents` (omission → `ERR_INVALID_REQUEST` 400) and its optional `reason` is discarded, not stored — `implementation/routes/settlements.py:143-160`.
- §3.5 — insert — ambiguity — Lane offering requires only lease existence; the ACTIVE/DEFAULTED lease-state gate applies at acceptance, not at offer time — `implementation/routes/lanes.py:23-50`.
- §3.7 — insert — ambiguity — Default-declaration settlement recompute runs on the provisional basis, so a maintenance override from an earlier reissue is not retained — `implementation/routes/leases.py:167-173`.
- §3.7 — insert — ambiguity — Cure-time escrow overpayment credit does not itself flip escrow `ACCUMULATING`→`FULL` or set `escrow_satisfied`; that flip is finalize-only — `implementation/routes/leases.py:200-207` (no status flip) vs `routes/settlements.py:188-195`.
- §3.8 — insert — ambiguity — Both buyout eligibility rules are evaluated before the `expected_lease_version` (OCC) comparison — `implementation/routes/buyout.py:47-66`.
- §3.8 — revise — ambiguity — Buyout acceptance applies escrow against quoted price plus the quote's *carried* arrears snapshot (not the lease's live arrears), and the lease's `arrears_cents`/`missed_payment_count` are left unchanged by acceptance — `implementation/routes/buyout.py:149-164`.

Everything else in the implementation (waterfall order and rounding, guarantee eligibility, state machines, cascades, error catalogue and statuses, RBAC table, OCC semantics, pricing ladder, bay buffer, warranty attribution, lazy doc expiry/classification recompute) was already uniquely pinned by the PRD and left untouched.
