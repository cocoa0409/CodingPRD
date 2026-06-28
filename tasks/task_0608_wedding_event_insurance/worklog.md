# Worklog — task_0608_wedding_event_insurance

## Step 1: Create Task Directory — 2026-06-21T14:27:00.000Z

Created `tasks/task_0608_wedding_event_insurance/` and `tasks/task_0608_wedding_event_insurance/workspace/` via `mkdir -p`. Pre-allocated directory used directly (no auto-indexing). Verified project-root `INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate Scaffold (Expert tier) — 2026-06-21T14:49:00.000Z

All constraints satisfied. The scaffold is complete and verified.

## Summary

I generated the three scaffold artifacts for **Task 0608 — Wedding & Special-Event Insurance** (WedSafe/Markel style) at the **Expert** difficulty tier, written purely from the scenario description and the scaffold-generator spec (no sibling tasks consulted).

**Files written** (all three, all valid YAML, `scaffold_lint.py` reports `VERDICT: clean lint`):
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Counts (Expert tier targets in parentheses):**
- Entities: **12** (10–15) — CoverageProduct, Vendor, ForceMajeureEvent, Policy, EventProfile, Coverage, Rider, Certificate, Endorsement, Claim, ClaimDocument, PremiumLedgerEntry
- Endpoints: **47** (15 GET / 32 POST) — above the 20–32 guideline band; the 32 POSTs are all load-bearing transitions across the 7 state machines (the GET surface was already trimmed to the FK-reverse-reach minimum). Rich transition surface kept since that is where the Expert difficulty lives, per the spec's "guidelines, not hard rules."
- Validations: **24** (18–30, ordered by priority)
- Calculations: **7** (3+) — rated_coverage_premium, rider_premium, policy_premium_reconciliation, cancellation_refund (dual-variant), claim_indemnity (dual-variant/3-way min), endorsement_premium_delta, claim_resubmit_cap
- State machines: **7 entries across 6 entities** (4+, including a **cycle** — Claim SUBMITTED↔INFO_REQUESTED — and a **parallel dimension** — Policy lifecycle_status × billing_status), plus Vendor's FLAGGED↔SOLVENT cycle and branching Certificate/Endorsement
- Errors: 46; Roles: 4 (PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster); Concurrency rules: 1 (OCC on Policy.version for endorsement apply)
- §1.8: **9 rule_ids × 2 = 18 instances**; §1.9: **38 instances (34 active + 4 excluded_because stubs)**

**Verified:** all 9 difficulty rules covered with differentiated instances; FK reverse-reachability clean; placeholder closure clean across both design files; all `grounds:` references resolve; formula-derived asserts computed as literals (e.g. premium 128000, sublimit indemnity 2500000, pro-rata earned 11250/refund 33750); OCC version inputs use `${var}`; no forbidden concurrency vocabulary; default clock `2026-01-01T00:00:00Z` declared; response envelope verbatim; file-split honored; instance names unique.

**One design decision worth noting:** Removed an auto-supersede side-effect from endorsement apply (and the SUPERSEDED state) so the OCC stale-version test is deterministic — each apply is an independent version-guarded write, keeping enum closure clean and avoiding a state-vs-OCC precondition-ordering conflict.

## Step 3: Copy Shared Files — 2026-06-21T14:51:00.000Z

Copied project-root `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T14:55:00.000Z

**Output written:** `workspace/PRD.md` (307 lines).

**Section structure:**
- **§1. Introduction** — 3 paragraphs framing the wedding/event-insurance product (deposit/vendor-failure/named-storm exposure, full policy lifecycle, contract-vs-narrative reading guidance).
- **§2. Global Specifications** (8 subsections): 2.1 RBAC (four roles, opaque identity, `policyholder_id` ownership key, `ERR_NOT_POLICY_OWNER` scope); 2.2 Response Structure (verbatim block); 2.3 Pagination; 2.4 Common Properties & Logical Clock (UUID `id`, ISO-8601 timestamps, `version`; `ClaimDocument`/`PremiumLedgerEntry` carry only `id`+`created_at`; clock default `2026-01-01T00:00:00Z`); 2.5 Money/Precision/Ledger; 2.6 Hierarchical Consistency/Cascades/Nested Retrieval; 2.7 OCC on endorsement apply; 2.8 Parallel policy state dimensions.
- **§3. Business Logic** (10 subsections): reference data; quoting & event profiles; coverage/rider selection; bind & premium reconciliation; pay/activate/expire; cancellation & free-look refund; claims filing & adjudication; certificates; endorsements (OCC stale-version framing + three delta variants); validation ordering.
- **§4. Endpoint Definitions** — 4-column table, all 47 scaffold endpoints.
- **§5. Error Code Catalogue** — 2-column table, all 46 real error IDs.

**Hard Contracts:** Contract 1 (field coverage 62/62) PASS; Contract 2 (rule coverage: validations, OCC, all state-machine transitions, 7 calculations, sibling-branch symmetry) PASS; Contract 3 (path purity in §3, 0 path tokens) PASS.

**Confirmation:** Neither withheld design file (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-21T14:58:00.000Z

Test infrastructure generation is complete.

**Both directories written:**
- `test_helpers/` — 9 modules: `__init__.py`, `types.py`, `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (full §5 catalog), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque-role headers + `make_policyholder_headers` for ownership threading), and a substantial `fixtures.py` (composite lifecycle/claim/endorsement setup helpers reused across both queues).
- `test_suite/` — `conftest.py` + 9 domain-named test files.

**Tests emitted:** 68 test functions across 9 files. 34 carry `Design: Difficulty/...` tags, 34 carry `Design: Corner/...` tags. Every test has exactly one Design tag, all verbatim-copied from the source YAML `name:` fields; no stray/unknown tags.

**Queue A (Difficulty) — 18 instances, 17 translated (≥2 tests each), 1 skipped:**
- All 9 rules' instances translated except **`priority_pair_validation_conflict/liquor_on_dry_policy_safety_beats_retired_product`**. Skip reason (PRD-first unique-derivability failure): scaffold asserts `ERR_LIQUOR_REQUIRES_ALCOHOL` (safety, p11) pre-empts `ERR_PRODUCT_RETIRED` (constraint, p12), but PRD §3.10 lumps safety and business-constraint checks together without committing to an order, and §3.3 prose lists the RETIRED guard *before* the liquor guard. Two PRD-only readers could ship either error, so ordering is not uniquely derivable. The rule's other instance (`pay_on_unbound_policy_state_beats_amount_mismatch`) IS uniquely derivable (PRD §3.5 lists lifecycle before amount) and got 2 tests.

**Queue B (Corner) — all 35 non-stub instances translated (≥1 test each), 0 skipped.** The 4 `excluded_because:` stubs (2 calculations + 2 errors) were verified to cross-reference real difficulty instances and correctly NOT translated.

**Verification performed:** all files byte-compile; `test_helpers` imports cleanly against the real `prd_bench_local_runner.testing` framework; all 68 tests collect under pytest with no import errors; every quoted PRD citation matches `PRD.md` verbatim; no `scaffold`/`Table N`/`§1.x` leakage in generated code.

## Step 6: Generate Implementation — 2026-06-21T14:58:00.000Z

Built a complete Python + Flask REST API for **Task 0608 — Wedding & Special-Event Insurance** in `workspace/implementation/`.

**File layout:** `start.sh` (reads $PORT, guarded pip install, exec foreground), `requirements.txt` (flask==3.0.3), `app.py` (blueprint registration + error handlers), `db.py` (in-memory Store dicts + UUID/common-field helpers), `clock.py` (logical clock default 2026-01-01T00:00:00Z), `timeutil.py`, `errors.py` (ApiError + full §5 catalog), `response.py` (envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `validators.py`, `serializers.py`, `routes/` (reference, policies, quote_items, certificates, endorsements, claims), `services/` (calculations, lookups, policy_ops).

**Framework/storage:** Flask, one blueprint per resource group. Storage in-memory only (plain Python dicts on a single `Store` in `db.py`). No SQLite, no file/JSON dump, no /tmp cache. Money uses `Decimal` with pinned `ROUND_CEILING`/`ROUND_FLOOR` per calculation contracts.

**Confirmations:** start.sh reads `$PORT` (default 10000), `app.run(host="0.0.0.0")`, foreground via `exec python3 app.py`, guarded pip install. In-memory, no seeding — `Store.__init__` only allocates empty dicts; no `seed_*` function; fresh boot reports total_count 0 for all entities. Every per-test-server restart wipes state.

**Behavior smoke-verified** (66 assertions, all passing): RBAC + auth ordering; envelope + pagination; premium reconciliation (sum-of-rounded-lines); rider clamp [2500,50000]; free-look inclusive `<=` boundary vs pro-rata `ceil(total*0.25)`; OCC stale version → 412; resubmit revision cap (≤3); claim indemnity three-way min + sublimit floor; coverage EXHAUSTED → policy CLAIMED_OUT; named-storm cutoff/landfall-window/vendor-not-defaulted; RAISE_ATTENDANCE delta; expire EVENT_NOT_ENDED gate; cascade voiding on cancel; ledger entries.

## Step 7: Run Tests and Iterate — 2026-06-21T15:12:00.000Z

All 8 parallel rounds clean — 68/68 passing in every round, zero failures and zero errors. The earlier intermittent single-test failures were confirmed to be host-contention server-restart timeouts (different random test each time, always a boot/connection error never an assertion), and this clean sweep confirms the implementation logic is correct and stable.

**Iterations run:** 1 logic-fix iteration, then 3 confirmation sweeps (final sweep: all 8 rounds 68/68).

**Root cause:** Exactly 2 tests failed deterministically in all 8 rounds of the initial sweep, both in `test_09_endorsements_occ.py`:
- `test_endorsement_apply_raise_attendance_bumps_premium_and_ledger`
- `test_occ_stale_policy_version_on_second_endorsement_apply`

Both failed with `404 ERR_REFERENCE_NOT_FOUND: "event_profile_id does not resolve"` on the first `RAISE_ATTENDANCE` endorsement apply.

**Diagnosis (per protocol):**
- STEP 1a/1b: PRD §3.9 verbatim covers and uniquely determines the RAISE_ATTENDANCE delta computation (delta = Σ over ACTIVE coverages of `per_guest_premium_cents` × attendance increase). The tests assert exactly this. Coverage and unique-derivability both pass — tests kept.
- STEP 2: The test payload `{"new_attendance": 250}` is PRD-faithful. PRD §3.9 declares the RAISE_ATTENDANCE payload as "a new attendance figure" (and SCAFFOLD.yaml confirms `{new_attendance}`) — the PRD never declares an `event_profile_id` payload field.
- STEP 3: The implementation over-specified by *requiring* `event_profile_id` and rejecting its absence — a field that traces to no PRD sentence. The PRD's phrase "sets the named event profile's expected_attendance" is unambiguous for a single-event policy (the sole profile is "the named" one).

**Fix applied to `implementation/`:**
- `workspace/implementation/routes/endorsements.py`, function `_apply_payload` (RAISE_ATTENDANCE branch): when `event_profile_id` is supplied it must resolve to a profile on the policy (`ERR_REFERENCE_NOT_FOUND` otherwise); when omitted and the policy has exactly one event profile, that sole profile is used as "the named event profile". This removed the spurious mandatory `event_profile_id` requirement while preserving the PRD-required attendance-raise behavior. The OCC test passed automatically once the first apply succeeded (the OCC version check already runs before payload application, so the stale second apply correctly returns `ERR_STALE_POLICY_VERSION` 412).

**Tests deleted:** None — both failing tests were PRD-faithful and correctly diagnosed as an implementation bug.

**Fixes applied to `test_helpers/`:** None.

**Note on flakiness:** Two intermediate sweeps showed one random test per sweep failing with `"could not be restarted"` / `ConnectionResetError(104)` — always a different test, always a server boot/connection error, never an assertion failure. Host-contention artifacts from 8 concurrent rounds each rebooting Flask before all 68 tests. The final sweep came back fully clean (8/8 rounds × 68/68).

## Step 8: Finalize PRD — 2026-06-21T15:20:00.000Z

Not skipped (Step 7 had 1 implementation/ fix). Output: `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 307 lines; PRD_FINALIZED.md = 307 lines. One paragraph (§3.9, line ~198) revised in place; ~0.3% lines modified.

**Changes (one bullet):**
- §3.9 Mid-Term Endorsements — revise — Pinned how RAISE_ATTENDANCE identifies the event profile to raise: `payload_json` carries `new_attendance` (positive int ≥ 1, else `ERR_INVALID_REQUEST`) and an optional `event_profile_id`. When supplied it must resolve to a profile on this policy (else `ERR_REFERENCE_NOT_FOUND`); when omitted, the sole profile is used if the policy has exactly one, otherwise `ERR_REFERENCE_NOT_FOUND`. — `routes/endorsements.py:155-187`

**Per-edit pre-edit search log:**
- (a) Subject: RAISE_ATTENDANCE endorsement payload — event-profile identification (`event_profile_id` optionality, resolution rule, single-profile fallback, `new_attendance` bound).
- (b) Impl paths enumerated/read: `routes/endorsements.py:155-187` (Step 7 site); `routes/endorsements.py:114-153` (ADD_COVERAGE/ADD_RIDER branches — confirmed scoping); `services/lookups.py:62-72` (`total_attendance`, `children_by_policy`); `routes/quote_items.py:43-88` (event-profile creation, `policy_id`, min-1 attendance); PRD §3.2 (SINGLE_EVENT = 1 profile, ANNUAL = many).
- (c) Wording adjustment: used "must resolve to an event profile belonging to this policy" (matches `policy_id` ownership check); scoped both unresolved-id and ambiguous-omission (0 or >1 profile) cases to `ERR_REFERENCE_NOT_FOUND`; left delta-computation prose untouched; no widening that touches ADD_COVERAGE/ADD_RIDER branches.

## Step 9: Complete PRD — 2026-06-21T15:25:00.000Z

Always runs. Source `PRD_FINALIZED.md` present → copied to `PRD_COMPLETED.md`, only the copy edited.

**Counts:** Lines 307 → 307 (all edits in-paragraph). Chars 49,080 → 50,876 (delta +1,796). Ambiguity-pins: **5**. Mismatch-revisions: **1**.

**Per-change log:**
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `validators.py:143-147`
- §3.1 Reference Data (CoverageProduct) — insert — ambiguity — second `ACTIVE` product for an already-covered `coverage_type` → `ERR_INVALID_REQUEST` — `routes/reference.py:68-70`
- §3.1 Reference Data (CoverageProduct) — insert — ambiguity — retiring a non-`ACTIVE` product → `ERR_INVALID_STATE` — `routes/reference.py:110-111`
- §3.3 Selecting Coverage Lines — insert — ambiguity — unresolved supplied `protected_vendor_id` → `ERR_REFERENCE_NOT_FOUND` — `routes/quote_items.py:116-117`
- §3.7 Filing Claims — insert — ambiguity — `coverage_id` must resolve to a coverage line on the same policy; cross-policy → `ERR_REFERENCE_NOT_FOUND` — `routes/claims.py:61-63`
- §3.7 ClaimDocument — revise — mismatch — `subject_kind`/`subject_ref` optional; absent `subject_kind` stored null (not defaulted to `NONE`); `subject_ref` stored verbatim/opaque, no resolution/rejection — `routes/claims.py:125-135`
- §3.9 Mid-Term Endorsements (ADD_COVERAGE) — insert — ambiguity — ADD_COVERAGE resolves only the product FK (`ERR_REFERENCE_NOT_FOUND`), creates the line directly `ACTIVE` without re-applying §3.3 guards, stores `protected_vendor_id` only when a string, adds delta to `total_premium_cents` only (no base/rider re-reconciliation) — `routes/endorsements.py:114-134`

**Deliberately unchanged:** `api_request_timestamp` wall-clock (consistent with §2.4); clock-set response/status (already pinned); ADD_RIDER + "total only" reconciliation (already pinned); intra-bucket ordering among §3.10 business-constraint checks (PRD intentionally lumps; no single impl order contradicted); `certificate_number` mint format (PRD leaves open, no client behavior depends on it).

---

## Pipeline Complete — 2026-06-21T15:25:00.000Z

All 9 steps done. Final state: 68/68 tests pass across all 8 parallel stability rounds. Task tree contains SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/, test_suite/ (9 files, 68 tests), workspace/ (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ with results.{1..8}.json all 68/68).
