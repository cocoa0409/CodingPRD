# Worklog — task_0253_marriage_license_vital_records

## Step 1: Create task directory — 2026-06-08T11:36:44.000Z

Created `tasks/task_0253_marriage_license_vital_records/` with `workspace/` subdirectory. Confirmed `./INSTRUCTION.md` exists at project root for Step 3.

## Step 2: Generate scaffold (Expert band) — 2026-06-08T12:01:00.000Z

Generated all three scaffold artifacts for **task_0253_marriage_license_vital_records** at the **Expert** difficulty band. `scaffold_lint.py` returns **VERDICT: clean lint** across all 629 setup/trigger calls (§1.8 + §1.9) with FK reverse-reachability satisfied.

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7) — 1371 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) — 1407 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) — 2030 lines

**Complexity profile:** primary archetype compliance_audit, secondary workflow_orchestration; flat multi-collection topology (api_prefix `""`); branching/cyclic state-machine shapes; segregation_of_duties role model; layers: optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation, scheduled_actions.

**Scale (Expert band):**
- **11 entities** — Applicant, Officiant, MarriageApplication, MarriageLicense, OfficiantReturn, MarriageRecord, CertifiedCopyRequest, AmendmentRequest, ApostilleRequest, FeeWaiver, FeeLedgerEntry (append-only, common_fields:false).
- **8 state machines** — including a branching application (DRAFT→{APPROVED,DENIED}), a cyclic amendment loop (SUBMITTED↔RETURNED_FOR_INFO), and a depth-3 cross-entity cascade (return-accept → license USED → record REGISTERED).
- **12 calculations** — waiting_period_window, validity_window, certified_copy_fee_calc (tiered + surcharge + gov-exempt + waiver absorption), amendment_fee_calc, waiver_cap_calc, applicant_age_years, remarriage_wait_check, return_filing_window, fixed_action_fees, officiant_ceremony_overlap, applicant_license_window_overlap, office_collected_balance.
- **13 validations** (precedence-ordered, priorities 1–11 with 9.5/9.7 inserts), **45 endpoints** (incl. `/_clock/set`, `/_clock/advance` + reverse-reachability GETs for every FK), **27 error codes**, **5 roles** (Applicant/Officiant entity_backed; Clerk/Registrar/WaiverOfficer opaque), **2 concurrency rules** (OCC on MarriageRecord.version and FeeWaiver.version at copy-issue, 412).

**Difficulty design (§1.8):** all 9 §0.5 rules × 2 instances = **18 instances**, each grounded in §1.1–§1.7 with precomputed literal asserts.

**Corner design (§1.9):** **45 instances** (40 active + 5 excluded_because stubs) across all 9 claim-extraction-guide sections.

## Step 3: Copy shared files — 2026-06-08T12:05:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-08T12:10:00.000Z

Generated `workspace/PRD.md` (292 lines, 47KB) — prose PRD for the Marriage License & Vital Records API.

**Structure:** §1 Introduction; §2 Global Specifications (9 subsections: RBAC for all 5 roles, response envelope verbatim, pagination, common properties + nested validation with FeeLedgerEntry common_fields:false exception, cascading state, precision/rounding, OCC, segregation of duties, fee ledger + collected-balance invariant); §3 Business Logic (10 subsections, scattered parameters); §4 45-endpoint table; §5 27-error table.

**Coverage (all PASS):** Contract 1 (Field-Name) — 62 required identifiers, 0 missing. Contract 2 (Rule Coverage) — all 27 error IDs in prose, both OCC rules, all 8 state machines, priority-ordered validation chain (3.10), 3 segregation-of-duties variants, all cascades, 24 calculation constants embedded. Contract 3 (§3 Path Purity) — 381 §3 backtick tokens scanned, 0 violations.

**Notable:** §3.8 juxtaposes the two overlap rules (strict-< symmetric 60-min buffer vs. half-open license window); late-return lateness pinned to return `created_at`; waiver refund-reversal path fully narrated. Hard constraint honored — neither design YAML was opened.

## Step 5: Generate unit tests — 2026-06-08T18:03:39.000Z

Test infrastructure generation is complete for `task_0253_marriage_license_vital_records`.

## Summary

I generated the full two-stage test suite by translating **only** the two design indices (no freelance walking of SCAFFOLD.yaml). All inputs were read in full, including the truncated tails.

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — 11 entity TypedDicts + status/role enums. `FeeLedgerEntry` correctly carries only `id`+`created_at` (common_fields: false); all others carry the full quartet.
- `api_client.py` — one method per PRD §4 endpoint (44 endpoints incl. `/_clock/set`, `/_clock/advance`).
- `api_errors.py` — 27-error `ApiErrorId` enum + HTTP status map, registered with the framework.
- `assertions.py` — per-entity assertions + `collected_balance()` / `find_ledger_entries()` invariant helpers.
- `factories.py`, `constants.py` (all calculation thresholds), `test_users.py` (opaque-id builders for segregation-of-duties + entity-backed builders for Applicant/Officiant), and a large `fixtures.py` with the shared 11-call chain (clock → applicants → application → approve → license → return → accept → record) plus waiver/copy/amendment/apostille/seal composites.

**Stage 2 — `test_suite/` (conftest + 6 files, 76 tests):**

Coverage is complete with **zero gaps**:
- **All 18 difficulty instances** (9 rules × 2) covered by **≥2 tests each** — including the four overlap/boundary instances that needed a second test added (officiant exactly-60-min-allowed, ceremony-at-valid-from registers record, before-valid creates no record, shared-applicant-approves-after-void).
- **All 40 active corner instances** covered by **≥1 test each**.
- **All 5 `excluded_because` stubs** verified to cross-reference real difficulty instances and correctly **not** translated.
- No phantom tags, no untagged/dual-tagged tests, no `skip`/`xfail`.

**Verification performed:**
- All 76 tests collect cleanly under the framework venv (`/private/tmp/prd312`); every test module imports without error.
- Every PRD citation confirmed verbatim in `workspace/PRD.md` (the 20 apparent mismatches were smart-quote/em-dash false positives in my matcher — each was grep-confirmed present).
- No scaffold-leakage strings, no unused imports, all files compile.

No instances were skipped — every design-index instance passed the PRD-first two-condition filter (the PRD prose is rich and the validation-ordering section §3.10 makes the priority-pair outcomes uniquely derivable).

One note: the tests assert behavior against `/_clock/set` and `/_clock/advance` exactly as the design indices drive them; these are PRD §3.9 administrative endpoints, so the temporal boundary tests are deterministic.

## Step 6: Generate implementation — 2026-06-08T18:03:39.000Z

The implementation is complete. Let me give a final summary.

## Summary

I generated a complete Python + Flask implementation of the **Marriage License & Vital Records API** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0253_marriage_license_vital_records/workspace/implementation/`.

### Structure
- `start.sh` — foreground launcher (`exec python3 app.py`), binds `0.0.0.0:$PORT` (default 10000), with a **guarded** dependency install (`if ! python3 -c "import flask"`) so per-test reboots don't re-run `pip install`.
- `app.py` — Flask entry point, blueprint registration, error handlers.
- `db.py` — in-memory store (starts **empty**, no seeding) plus a logical clock (`/_clock/set`, `/_clock/advance`).
- `errors.py`, `response.py`, `middleware.py`, `util.py`, `constants.py` — foundation: error catalog, the exact `meta`/`response_type`/`data` envelope, auth (`X-User-ID`/`X-User-Role`), and ISO-8601-with-3-fractional-digits timestamps.
- `routes/` — one file per resource group (11 resource groups + clock); all 44 endpoints from the PRD table.
- `services/` — calculations, ledger, derived counts, license lifecycle.

### Key correctness decisions (verified via smoke tests)
- **Response envelope / pagination** match the scaffold exactly (`limit`/`offset`/`total_count`/`has_more` in `meta`; defaults 10/min 1/max 100/offset 0; ascending by `created_at`).
- **FeeLedgerEntry** is the sole entity without `updated_at`/`version` (verified — only `id`+`created_at` plus its data fields).
- **Calculations** all produce exact spec values: license fee 9000, tiered copy fee (1500×≤3 + 900×extra), confidential surcharge 2500, government exemption (fee→0), amendment fee with **round-each-component-then-sum** (CLERICAL 2300; SUBSTANTIVE w/ 1 resubmit 6250), waiver caps 6000/3000 by the 0.50 shortfall ratio, apostille 4000, late surcharge 2000.
- **Boundary operators** per PRD: waiting period inclusive (`ceremony >= valid_from`), expiry strict (`clock > expires_at`), officiant buffer strict-`<` 60 min (exactly 60 apart allowed), license overlap half-open (touching endpoints don't overlap), remarriage wait inclusive.
- **Validation ordering** follows PRD §3.10: auth(401)→forbidden(403)→not-found(404)→invalid-request(400)→OCC(412)→state(409)→business rules. The accept-return precondition sequence follows PRD §3.4 prose order (segregation **last**), which the skill mandates over the scaffold's priority numbers.
- **OCC** uses `expected_record_version`/`expected_waiver_version` on the certified-copy decision only.
- **Segregation of duties** enforced on all three flows (return accept, waiver-consuming copy issue, substantive amendment).
- **Cascades**: accept-return → license USED → MarriageRecord REGISTERED; license expire/sweep → application EXPIRED; void → REFUND reversal; refund → waiver absorption reversal (CONSUMED→GRANTED). Each affected entity independently bumps `version`/`updated_at`.

### Verified
- Full happy-path workflow end to end, plus ~40 edge cases (age/consent boundaries, remarriage wait, duplicate/married applicants, double-booking, license overlap, confidential access, waiver absorb/consume/refund, expiry sweep, seal blocking, validation precedence, invalid-request shapes).
- Clean fresh boot starts with an empty store (no carry-over state); `start.sh` launches and serves correctly. All modules compile under the environment's Python 3.9.6 / Flask 3.0.3.

One note for the caller: `total_charged_cents` is implemented as the sum of **CHARGE** rows only (not net of refunds), per the explicit scaffold/PRD definition — so after a void it remains at the gross charged amount while the ledger separately carries the offsetting REFUND. This is the spec's intended semantics.

## Step 7: Run tests and iterate — 2026-06-08T18:13:31.000Z

Two consecutive 8-round sweeps fully clean (16 rounds total, 76/76 each). The flake is resolved. Exiting with the summary.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps.
- Sweep 1 (baseline): 71/76 in all 8 rounds — 5 deterministic failures.
- Sweep 2 (after the 4 logic fixes): 76/76 in 7 rounds, one round dropped 1 test to a transient connection abort under peak load.
- Sweep 3 + a confirmation sweep (after server hardening): 76/76 in all 8 rounds, twice in a row.

**Tests deleted:** none. Every failing assertion was verbatim-covered by PRD and uniquely derivable; all five failures were test_helpers / test-ordering / implementation bugs, not PRD-silence.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `create_two_applicants()` — the helper passed `full_name`/`date_of_birth` both as hardcoded keyword defaults and via `**a_overrides`/`**b_overrides`, raising `TypeError: got multiple values for keyword argument 'full_name'` whenever a caller supplied those keys. Rebuilt the kwargs as a merged dict so caller overrides take precedence. (Fixed `test_application_approve_creates_license_and_charge` and `test_application_deny_creates_no_license_records_reason`.)

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_certified_copies_fees.py`, `test_government_can_issue_copy_on_sealed_record` and `test_sealed_record_is_confidential_and_government_copy_succeeds` — both created a PENDING certified copy *before* sealing, so the seal step correctly failed with `ERR_RECORD_HAS_PENDING_COPIES` (PRD 3.5: sealing "is blocked if any certified-copy request for the record is still PENDING"). The implementation check is PRD-mandated and was left intact; reordered each test's setup to seal first, then create and issue the GOVERNMENT copy on the now-SEALED record — the one requester PRD explicitly permits. Assertions (ISSUED status, fee 0) unchanged.

**Fixes applied to `implementation/`:**
- `routes/licenses.py`, `void_license()` — error-precedence bug. A `USED` license (consummated by an accepted return) hit the generic `status != "ISSUED"` gate first and returned `ERR_INVALID_STATE`. PRD 3.3 names the exact error for this condition: "If any accepted return references the license, the void is rejected with `ERR_LICENSE_ALREADY_USED`." Moved the `has_accepted_return` check ahead of the generic state gate. (Fixed `test_license_void_already_used_rejected`.)
- `app.py` / `requirements.txt` / `start.sh` — flakiness hardening (not a logic change). Under the 8-round concurrent sweep the Werkzeug dev server occasionally dropped a connection mid-request (client saw `BadStatusLine` on `POST /returns/.../accept` in 1 of 8 rounds). Switched the WSGI server to waitress (threads=8, backlog=256) with a graceful fallback to the threaded dev server if waitress is unavailable; added `waitress>=3.0.0` to requirements and the start.sh install guard. Storage remains in-memory; no data is seeded. (Fixed the intermittent `test_public_copy_issue_on_sealed_record_stays_pending` connection drop.)

**Feedback for generators:** no Zero-Silence or unique-derivability misses surfaced — all five failures were mechanical (a kwargs collision in a fixture, a test setup ordering that violated a PRD precondition, an implementation error-precedence ordering, and an environmental connection flake), none traceable to PRD silence or scaffold-only assertions.

## Step 8: Finalize PRD — 2026-06-08T18:16:27.000Z

`PRD_FINALIZED.md` has been created as an exact copy of `PRD.md`, with **zero edits**. After full analysis, none of the four `<step_7_diff>` items traced to PRD-silence or PRD-mismatch — every one was a mechanical bug whose correct behavior the PRD already uniquely determines.

## Summary

**Line counts:** PRD.md = 292 lines, PRD_FINALIZED.md = 292 lines. **Delta: 0 lines (0.0%).** Files are byte-identical.

**Changes:** None. No PRD edits were warranted.

**Note on workspace:** This workspace contains only `PRD.md`, `PRD_FINALIZED.md`, `INSTRUCTION.md`, and `implementation/`. There is no `test_suite/` or `test_helpers/` directory present, so I aligned strictly against `implementation/` (the stated alignment target) and the step_7_diff narrative.

### Per-item analysis (every step_7_diff item got the mandatory pre-edit search; all concluded no-edit)

1. **`test_helpers/fixtures.py` kwargs collision** — Subject: test-fixture construction. Enumerated paths: none in `implementation/` (test-only helper). Pure `TypeError` from duplicate keyword args in a fixture; no implementation behavior and nothing the PRD describes. No edit.

2. **`test_suite/test_04` sealed-record ordering** — Subject: sealing a record with a PENDING certified copy, and issuing a GOVERNMENT copy on a SEALED record. Enumerated/read paths: `routes/records.py::seal_record` (lines 46-62: REGISTERED/AMENDED-only state gate, `ERR_RECORD_HAS_PENDING_COPIES` PENDING-copy block, force `is_confidential=True`) and `routes/certified_copies.py::decide_copy` (lines 119-167: sealed→GOVERNMENT-only via `ERR_RECORD_SEALED`, government exemption zeroing the gross → fee 0, status ISSUED). Both match PRD 3.5 and 3.6 verbatim. The failure was a test-setup ordering that violated a PRD-mandated precondition, not PRD silence. No edit.

3. **`routes/licenses.py::void_license` error-precedence** (the only implementation logic change) — Subject: voiding a license referenced by an accepted return (a USED license). Enumerated/read paths: `routes/licenses.py::void_license` (lines 39-64), `routes/licenses.py::expire_check` (lines 23-36), and `services/license_ops.py` (`has_accepted_return`, `expire_license`, `sweep_expired`). PRD 3.3 "Voiding" already pins the precedence: "If any accepted return references the license, the void is rejected with `ERR_LICENSE_ALREADY_USED`" — stated before the "Otherwise the license moves from `ISSUED` to `VOID`" transition. The fix moved impl into agreement with the already-determined PRD ordering; no residual silence or mismatch. No edit.

4. **`app.py` / `requirements.txt` / `start.sh` server hardening** — Subject: WSGI server / concurrency. Infrastructure only (waitress swap, threads/backlog), explicitly "not a logic change"; storage stays in-memory, no seeding. PRD specifies no WSGI server. No behavioral silence. No edit.

This is consistent with the step_7 author's own conclusion: "no Zero-Silence or unique-derivability misses surfaced — all five failures were mechanical." A fresh implementer reading PRD_FINALIZED.md (= PRD.md) reproduces the current implementation's behavior on all four subjects.

## Step 9: Complete PRD — 2026-06-08T18:21:21.000Z

## Summary

**Source vs output:** `PRD_FINALIZED.md` (292 lines, 47029 chars) → `PRD_COMPLETED.md` (292 lines, 48470 chars). Char-delta: **+1441**. Line count unchanged (all edits are in-paragraph inserts/revisions; no new sections or paragraphs).

**Counts:** 5 ambiguity-pins, 1 mismatch-revision.

**Changes (one per edit):**

- **§3.2 (The approval decision)** — revise — mismatch — PRD said `denial_reason_code` was "supplied or derived," but impl never derives one; pinned to "exactly as supplied … null when the body omits it; the server derives no reason of its own" — `routes/applications.py:146-149`.
- **§3.2 (eligibility screen)** — insert — ambiguity — PRD left the inter-check ordering unspecified when multiple eligibility checks fail; pinned the impl order: age (party A then B), then remarriage (party A then B), then concurrent-license overlap — `routes/applications.py:155-163`.
- **§3.3 (Expiry checking)** — insert — ambiguity — PRD was silent on expire-check against a non-`ISSUED` license; pinned that a `USED`/`EXPIRED`/`VOID` license yields `ERR_INVALID_STATE` before the clock is consulted — `routes/licenses.py:27-28`.
- **§3.3 (Voiding)** — insert — ambiguity — PRD did not state precedence between the accepted-return check and the state gate; pinned that the accepted-return check (`ERR_LICENSE_ALREADY_USED`) runs first, and a non-`ISSUED` license with no accepted return yields `ERR_INVALID_STATE` — `routes/licenses.py:47-50`.
- **§2.7 (OCC)** — insert — ambiguity — PRD was silent on `expected_waiver_version` supplied with no `fee_waiver_id`, and on record-vs-waiver check ordering; pinned that the supplied version can't match (→ `ERR_STALE_VERSION`) and that the record-version check precedes the waiver-version check — `routes/certified_copies.py:99-106`.
- **§2.3 (Pagination/ordering)** — insert — ambiguity — PRD's "sorted by creation timestamp ascending" left ties unspecified; pinned the secondary insertion-sequence tiebreak the impl applies — `services/common.py:72-74`, `util.py:46-60`.

**Behaviors checked and found already pinned (no change):** age-boundary granularity, remarriage 30-day boundary, license valid_from/expires_at inclusivity, officiant double-booking strict-<60min vs half-open license-overlap, certified-copy fee order (tier→surcharge→gov-exempt→waiver) and rounding, amendment fee component-wise round-half-up, waiver means-test and cap, ledger collected-balance invariant, seal/confidential access precedence, segregation-of-duties points, and clock empty-data responses (covered by §2.2).
