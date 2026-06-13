# Worklog — task_0210_product_warranty_claims

Scenario: 210. Product Warranty Registration & Claims: product/serial registration, warranty term & coverage tiers, extended-warranty purchase, claim intake/RMA, repair vs replace vs refund, proof-of-purchase validation, depreciation/proration, warranty transfer

## Step 1: Create task directory — 2026-06-07T00:00:00.000Z

Created `./tasks/task_0210_product_warranty_claims/workspace`. Next index determined as 0210 (highest existing = 0209).

## Step 2: Generate scaffold — 2026-06-07T00:00:00.000Z

First subagent generated SCAFFOLD.yaml (1191 lines; 13 top keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) and SCAFFOLD_DIFFICULTY_DESIGN.yaml (1265 lines, §1.8 depth index), then hit a 529 Overloaded error before writing the corner file. A second fresh subagent (reading SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml for consistency) generated the missing SCAFFOLD_CORNER_DESIGN.yaml (2941 lines, §1.9 breadth index). Verbatim summary of the completion subagent:

> Generated SCAFFOLD_CORNER_DESIGN.yaml — single top-level key `scaffold_corner_design`, derived strictly from the existing SCAFFOLD.yaml (§1.0–§1.7) and complementing the §1.8 depth instances.
> Result: `VERDICT: clean lint` from `scaffold_lint.py` (34 endpoints, 9 entities, 56 §1.9 full instances scanned, 640 calls scanned across §1.8+§1.9 — all conform to §1.5 input/role/output; all FKs reverse-reachable).
> Corner instances emitted: 80 total (56 full `test_recipe` instances + 24 `excluded_because` stubs), broken down by the 9 claim-extraction-guide sections: entities 13, state_machines 11, calculations 8, validations 13, endpoints 8, errors 15, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1.
> Coverage breadth: entity creation/retrieval/listing/not-found/required-fields/defaults/computed/system-fields/enum+range constraints/immutability(Owner)/FK integrity+reverse-reachability; state-machine invalid-from rejections, terminal lockdown, idempotency, initial-state, valid transitions (expiry sweep, withdraw, void cascade) and precondition enforcement; calculation correct-result/constants/precision/boundary variants (msrp clamp, transfer-fee tier boundary at 36mo, floor-vs-coverage cap, COVERAGE_FLOOR clamp); every validation rule's violation→error including proof rejection-reason ordering (DATE before AMOUNT); endpoint action/computed-read side-effects + all five filtered-list FK reverse-reachability GETs; all 15 error_ids verified triggerable; peer-role RBAC denials + ownership (ERR_NOT_OWNER) + shared-op success; OCC version-increment + happy-path + stale-version (412); derived-field reconciliation; immediate consistency.
> All entity/field/state/error/endpoint/calculation names match SCAFFOLD.yaml verbatim; every corner name unique and disjoint from §1.8; formula-derived asserts computed in code and pinned as literals.

Note: scaffold generation isolation honored (no sibling-task peeking).

## Step 3: Copy shared files — 2026-06-07T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0210_product_warranty_claims/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T00:00:00.000Z

PRD generated at `workspace/PRD.md` (255 lines, ~5,700 words). Design YAMLs withheld (read SCAFFOLD.yaml only). Verbatim subagent summary:

> Structure: §1 Introduction (3 paragraphs: dual depreciation algorithms + reconciling ledger + three operators). §2 Global Specifications — 10 subsections: RBAC (Owner entity-backed; WarrantyAdmin/ClaimsProcessor opaque, latter records `claims_processor_user_id`), verbatim §2.2 envelope, Pagination, Common Resource Properties (Owner/WarrantyTransfer/LedgerEntry carry only id/created_at — no updated_at/version), Path Resolution, Monetary Precision, Coverage Ledger Reconciliation, OCC, Hierarchical Cascades, Validation Ordering. §3 Business Logic — 13 subsections (catalogue → owners/registration → proof/activation → extended warranties → claim filing → RMA → adjudication → refund depreciation → premium refund → fulfillment → transfer → transfer fee → void/expiry). §4 — 35-endpoint 4-column routing table. §5 — 15-error 2-column table.
> Hard contracts all PASS: Contract 1 (Field-Name Coverage) 53 identifiers, 0 missing; Contract 2 (Rule Coverage) all 15 error IDs + constants (0.97 decay, 90-day window, 500-cent tolerance, 10% short-rate penalty, 1500/2500/4000 transfer rates, 1000-cent surcharge/floor, 30-day cooldown) + all states/enums + 5 ledger reasons; Contract 3 (§3 Path Purity) 279 tokens, 0 violations.
> Notable decisions: refund-depreciation evaluation order pinned (round-half-up before remaining-coverage cap; pre-adjudication ledger read); both depreciation variants (STRAIGHT_LINE/DECLINING_BALANCE) and both premium-refund variants (PRO_RATA/SHORT_RATE) rendered with equal density incl. divergence note + T==0 zero-refund edge; OCC framed purely as stale-version rejection (expected_registration_version / version mismatch / ERR_STALE_VERSION / 412); half-open coverage-overlap adjacency + closed 30-day cooldown buffer stated with exact boundary inclusivity; transfer-fee conservation invariant (reject → REVERSAL credit → coverage restored, owner unchanged) and refund-terminates-coverage cascade (void + cancel active extensions) fully described.

## Step 5: Generate unit tests — 2026-06-07T00:00:00.000Z (concurrent with Step 6)

Verbatim subagent summary:

> Generated complete test infrastructure from the two design indices (the only test source), with full PRD-first adjudication.
> Tests emitted: 92 total — Queue A (Difficulty) 36 tests (all 18 difficulty instances covered by exactly 2 tests each), Queue B (Corner) 56 tests (all 56 non-stub corner instances covered by ≥1 test each).
> Instances skipped under the PRD-first filter: 0. Every asserted rule (depreciation formulas, transfer-fee tiering, validation-priority pairs, cascade chains, OCC, cooldown/overlap interval semantics, reconciliation) has verbatim, uniquely-derivable PRD prose in §2–§3. The 24 corner `excluded_because:` stubs were correctly NOT translated (assertions owned by cited §1.8 difficulty instances); all stub cross-references resolve to real difficulty instances.
> Audits passed: Difficulty coverage 18/18 with ≥2 tests; Corner coverage 56/56 non-stub with ≥1 test; tag integrity 0 ghost tags, every test has exactly one Design: line + PRD citation; verbatim citation — all 124 citation fragments (≥8 words) survive literal grep of PRD.md; no skip/skipif/xfail; no scaffold/Table N/§1.x leakage; all files compile; every api.*/F.* reference resolves.
> File layout — test_helpers/: types.py (TypedDicts, Owner/WarrantyTransfer/LedgerEntry carry only id+created_at), api_client.py (one method per §4 endpoint), api_errors.py (15 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (Owner entity_backed w/ make_owner_headers; WarrantyAdmin/ClaimsProcessor opaque), fixtures.py (composite setups: active-validated registration, registration+extension, claim-in-RMA, adjudicated-refund, pending-transfer), __init__.py. test_suite/: conftest.py + 8 domain files simple→complex (test_01_catalogue_and_registration … test_08_coverage_ledger_and_listing).
> Load-bearing computed values copied verbatim: 37500/34692 SL-vs-DB refund divergence, 9000/8100 PRO_RATA-vs-SHORT_RATE premium divergence, 3500 APPLIANCE transfer fee, 30000 pre-debit cap binding, 4167 round-half-up boundary.

## Step 6: Generate implementation — 2026-06-07T00:00:00.000Z (concurrent with Step 5)

Verbatim subagent summary:

> Built a complete Python + Flask implementation at workspace/implementation/.
> File layout: start.sh (executable), requirements.txt (flask==3.0.3), app.py (blueprint registration + error handlers, binds 0.0.0.0:$PORT), db.py (in-memory stores — 9 entity dicts + logical-clock singleton + monotonic insertion counter; nothing seeded), errors.py (APIError + exact error-id constants), response.py (envelope helpers meta/response_type/data; pagination limit/offset/total_count/has_more), middleware.py (X-User-ID/X-User-Role auth, three roles, 401-before-403 ordering), routes/ (products, coverage_tiers, owners, registrations, extended_warranties, proofs, claims, clock), services/ (calc.py 4 calc rules + round-half-up, timeutil.py whole-month + calendar-month arithmetic, registration_svc.py ledger reconciliation/active-tier+end-date recompute/version bumps/serialization, common.py body parsing/pagination/field validators).
> start.sh: reads PORT (default 10000), binds 0.0.0.0, runs exec python3 app.py foreground; pip install guarded by `python3 -c "import flask"` so per-test reboots skip reinstall. Verified boots + answers HTTP ~1s, store empty on fresh boot, no disk state.
> Verified behavior: catalog/owner/registration creation, proof validation cascading REGISTERED→ACTIVE, claim file→RMA→adjudicate→fulfill, both depreciation algorithms (SL 90000*53/60; DB 90000*0.97^7=72718), refund cap (read pre-adjudication remaining, cap last), premium refund (PRO_RATA + SHORT_RATE 10% penalty), transfer fee tiers + APPLIANCE surcharge + floor/cap order, OCC stale-version (412), transfer accept/reject with ledger reversal + coverage conservation, expiry sweep, cooldown closed-buffer boundary (30d→409, 31d→201), half-open coverage overlap, validation precedence (401→403 FORBIDDEN→404→409→412→403 NOT_OWNER→422 business→400).
> Under-determined decisions made: (1) "highest-coverage tier" for active_tier_id = in-force tier (BASE + ACTIVE extensions) with greatest coverage_cap_cents, tie-broken by insertion order. (2) Proof rejection_reason: PRD defines two substantive checks (90-day date window, 500-cent amount tolerance) but lists three reason codes; maps date-window fail→DATE_MISMATCH, amount fail→AMOUNT_MISMATCH (date checked first); EXPIRED_WINDOW never emitted (no distinct trigger defined). (3) Deny gating: §3.7 gates approval (defect/refund/fiscal checks); a deny decision from RMA_ISSUED allowed unconditionally. (4) Issue-RMA eligibility errors: registration-not-ACTIVE or proof-not-VALIDATED both → ERR_WARRANTY_EXPIRED, reserving ERR_INVALID_STATE for the claim's own state. (5) created_at ordering: ms-precision timestamps, list sort uses hidden monotonic _seq counter (stripped from output) for stable same-ms ordering.

## Step 7: Run tests and iterate — 2026-06-07T00:00:00.000Z

Long-lived fix subagent ran the loop to a clean 8-round parallel sweep. Orchestrator independently re-ran the 8-round sweep afterward to confirm: all 8 rounds 92/92 passed, 0 failures. Verbatim subagent summary:

> **Iterations run:** 2 sweeps (initial baseline + one fix round). Final sweep: all 8 parallel rounds 92/92, zero failures, zero flakiness.
> **Baseline:** 68/92 passing, stable across all 8 rounds (24 unique failures, all deterministic — no flakiness).
> **Root causes (two distinct):**
> 1. **Decision-value casing mismatch (22 of 24 failures).** The adjudication payloads sent `decision: "APPROVE"` / `"DENY"` (uppercase), but the PRD prose (§3.7: "supplying a `decision` to either approve or deny it") and the SCAFFOLD (`approve:`/`deny:` transition triggers) both use lowercase. The implementation correctly accepted lowercase `approve`/`deny`. This was a **test bug**, fixed in the test layer to be faithful to PRD prose.
> 2. **issue-rma error-precedence (1 failure: `test_issue_rma_blocked_when_registration_still_registered`).** A REGISTERED (not-yet-ACTIVE / unvalidated-proof) registration was returning `ERR_WARRANTY_EXPIRED` when the test (faithful to PRD §2.10 priority order + §3.6 transition preconditions, confirmed by SCAFFOLD priority table: state=priority 4 → `ERR_INVALID_STATE`, warranty-window/EXPIRED=priority 8 → `ERR_WARRANTY_EXPIRED`) expected `ERR_INVALID_STATE`. This was an **implementation bug**.
> The remaining 2 failures (`test_state_beats_safety_*`) and several others were downstream of cause 1.
> **Tests deleted:** None. Every failing assertion traced verbatim to PRD prose and was uniquely derivable.
> **Fixes applied to `test_helpers/`:**
> - `factories.py` — `adjudicate_approve_payload` / `adjudicate_deny_payload`: changed `decision` literal from `"APPROVE"`/`"DENY"` to `"approve"`/`"deny"` to match the PRD's lowercase decision verbs.
> **Fixes applied to `test_suite/`** (inline payloads, same casing bug as the factory):
> - `test_04_refund_depreciation.py` (1 occurrence) and `test_07_validation_and_rbac.py` (7 occurrences) — inline `{"decision": "APPROVE", ...}` literals lowercased to `"approve"`.
> **Fixes applied to `implementation/`:**
> - `routes/claims.py`, `issue_rma()` — split the conflated eligibility check so that an `EXPIRED` registration still yields `ERR_WARRANTY_EXPIRED` (priority 8), but any other non-ACTIVE status or unvalidated proof now yields `ERR_INVALID_STATE` (priority 4 state precondition), per PRD §2.10/§3.6 and the SCAFFOLD priority table.
> No implementation checks were weakened, no endpoints/fields added, and storage remains in-memory only.

## Step 8: Finalize PRD — 2026-06-07T00:00:00.000Z

PRD_FINALIZED.md produced (one targeted edit). Verbatim subagent summary:

> Line counts: PRD.md 255 → PRD_FINALIZED.md 255 (0% line-count delta; one line revised in place).
> Changes: §3.6 (Return Logistics: Issuing the RMA) — revise — Replaced the ambiguous error clause "a reported date past the warranty end (or a registration no longer eligible) is rejected with `ERR_WARRANTY_EXPIRED`" with an explicit error-precedence mapping: only an `EXPIRED` registration (and a reported-date-past-warranty-end) yields `ERR_WARRANTY_EXPIRED` (priority 8); any other illegal transition condition — registration not `ACTIVE` (REGISTERED / TRANSFER_PENDING / VOIDED), `proof_status` not `VALIDATED`, or claim not `INTAKE` — yields `ERR_INVALID_STATE` (priority 4) — routes/claims.py:138-156.
> Pre-edit search log — Edit 1 (§3.6 error mapping): (a) Subject: issue-rma (INTAKE→RMA_ISSUED) precondition guards and which conditions map to ERR_INVALID_STATE (priority 4) vs ERR_WARRANTY_EXPIRED (priority 8). (b) Impl paths enumerated/read: routes/claims.py:134-163 issue_rma() (Step 7 site — verified order claim≠INTAKE→ERR_INVALID_STATE; reg EXPIRED→ERR_WARRANTY_EXPIRED; reg≠ACTIVE OR proof≠VALIDATED→ERR_INVALID_STATE; reported_date past warranty_end→ERR_WARRANTY_EXPIRED), routes/claims.py:54-108 file_claim() §3.5 parallel warranty-window path (EXPIRED→ERR_WARRANTY_EXPIRED only, no proof/ACTIVE check — edit scoped to §3.6 only), routes/clock.py:31-52 advance_clock() expiry sweep (EXPIRED reachable only from ACTIVE, so REGISTERED never EXPIRED → correctly falls to ERR_INVALID_STATE branch), routes/registrations.py:130-256 transfer/void guards (independently use ERR_INVALID_STATE; §3.6 wording makes no claim about them). (c) Wording adjustment: scoped the sentence strictly to the issue-rma transition, enumerated non-ACTIVE statuses as "for example" not exhaustive universal, tied each branch to its §2.10 priority number — consistent with §3.5 and transfer/void guards without over-claiming.
> Cause 1 (decision casing) — no PRD edit: implementation accepts lowercase approve/deny (DECISIONS = {"approve","deny"}), already matching PRD §3.7 verbatim; Step 7 fixed this entirely in test factories/inline payloads (pure fixture bug), so no pin needed.

## Step 9: Complete PRD — 2026-06-07T00:00:00.000Z

PRD_COMPLETED.md produced via full PRD-vs-implementation scan. Implementation and tests unchanged since the verified Step 7 sweep (Step 9 edits PRD_COMPLETED.md only), so no re-run needed. Verbatim subagent summary:

> Files: Source PRD_FINALIZED.md (255 lines, 39,537 chars) → PRD_COMPLETED.md (255 lines, 41,209 chars). Char delta: +1,672. No lines added/removed — all edits in-paragraph.
> Counts: 1 mismatch-revision, 9 ambiguity-pins (across 9 edited paragraphs).
> Per-change:
> - §2.3 Pagination — insert — ambiguity — out-of-range limit/offset are clamped (limit→[1,100], negative offset→0) rather than rejected; non-integer limit/offset → ERR_INVALID_REQUEST — services/common.py:45-57
> - §3.1 Products — insert — ambiguity — duplicate model_number rejected with ERR_INVALID_REQUEST (400) — routes/products.py:31-33
> - §3.1 Coverage tiers — insert — ambiguity — duplicate (product_id, tier_name) rejected with ERR_INVALID_REQUEST (400) — routes/coverage_tiers.py:45-48
> - §3.2 Owners — insert — ambiguity — duplicate email rejected with ERR_INVALID_REQUEST (400) — routes/owners.py:25-27
> - §3.2 Registration — insert — ambiguity — if the product has no BASE tier at registration, active_tier_id is null and remaining_coverage_cents is 0 — routes/registrations.py:77-89, services/registration_svc.py:120-121
> - §3.3 Proof submission — insert — ambiguity — submission is not ownership-scoped; an Owner caller need not own the registration, no ERR_NOT_OWNER — routes/proofs.py:19-35
> - §3.3 Proof validation — revise — mismatch — PRD listed three checks (date/amount/window) and code EXPIRED_WINDOW; impl runs only a single symmetric (absolute, either-direction) 90-day date check yielding DATE_MISMATCH, then amount yielding AMOUNT_MISMATCH; EXPIRED_WINDOW never emitted; boundaries (exactly 90 days / exactly 500 cents) pass — routes/proofs.py:64-83
> - §3.4 Extension purchase — insert — ambiguity — purchase is not ownership-scoped (no ERR_NOT_OWNER); the coverage-interval effective moment is the server's logical clock — routes/extended_warranties.py:36-63
> - §3.4 Extension cascade — insert — ambiguity — effective_date is the logical-clock instant; "highest-coverage tier in force" defined as greatest coverage_cap_cents (BASE always in force), ties broken to earliest-created tier — routes/extended_warranties.py:79, services/registration_svc.py:93-98
> - §3.9 Premium refund / §3.12 Transfer fee — insert — ambiguity — "current time" pinned as the server's logical-clock instant (not wall clock) for both elapsed-month computations — routes/extended_warranties.py:114, routes/registrations.py:172
> Notes: behaviors already uniquely pinned by PRD (validation-priority order, depreciation/refund formulas, ledger reconciliation, state machines, RBAC table, common-field shapes, transfer OCC) needed no change. The one mismatch (proof EXPIRED_WINDOW / three-check ordering) confirmed against impl and test_02_proof_validation.py. Low-value non-deterministic details (e.g., rma_number string format) left as-is.

---

## PIPELINE COMPLETE

All 9 steps finished. Final state: 92 tests, all passing across an 8-round parallel per-test-server stability sweep (independently re-confirmed by orchestrator: rounds 1–8 each 92/92, 0 failures). Artifacts present: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/, test_suite/ (8 files), workspace/implementation/ (Flask, in-memory).
