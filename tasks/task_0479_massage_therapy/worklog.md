# Worklog — task_0479_massage_therapy

Scenario: Massage Therapy Practice: therapist license & modality, appointment & room/table, intake & SOAP/contraindication, membership/package & rollover credit, insurance/HSA & superbill, gratuity & commission, draping/consent policy, no-show fee

Difficulty: Expert tier (scaffold-generator §0.4 Expert band) — passed to Step 2 only.

## Step 1: Create task directory — 2026-06-24T02:48:40.000Z

Created `tasks/task_0479_massage_therapy/` and `tasks/task_0479_massage_therapy/workspace/` (pre-allocated directory; no index scan performed).

## Step 2: Generate scaffold (Expert tier) — 2026-06-24T03:14:00.000Z

Everything is correct. The file split is honored: SCAFFOLD.yaml contains §1.0–§1.7 (no design keys), and each design file has exactly its single top-level key.

All three artifacts are complete, internally consistent, and pass `scaffold_lint.py` cleanly. Here is the summary.

## Summary

Generated a complete **Expert-tier** scaffold for `task_0479_massage_therapy`. All three files written and validated.

**Complexity profile:** temporal_windowing (primary) + pricing_engine (secondary); flat topology, parallel state-machine shape, peer-roles model. Layers: scheduled/deferred actions (logical clock), rate/threshold triggers, derived-field reconciliation, optimistic concurrency.

**Scale:**
- **14 entities** — Modality, Therapist, TherapistCertification, Table, Client, Intake, ConsentRecord, MembershipPlan, Package, CreditLedgerEntry (append-only, common_fields:false), CommissionTier, Appointment, SoapNote, Superbill.
- **6 state machines** — Appointment (parallel axes: `scheduling_status` × `settlement_status`), Package (cyclic ACTIVE↔SUSPENDED + self-loop renew), SoapNote (DRAFT→FINALIZED→DRAFT→AMENDED amendment loop), Intake, ConsentRecord, Superbill. Non-linear shapes on multiple entities; revert/compensation transitions (waive-no-show, void-refund, reopen).
- **5 calculations** — `service_pricing` (member discount variants), `client_owed_resolution` (wallet waterfall), `no_show_fee_proration` (tiered by lead-time × strike multiplier, multiply-then-round), `tiered_commission` (marginal slice across MTD-revenue bands, net of gratuity, FLAT vs TIERED variants), `package_rollover` (cap-then-grant). All money in integer cents with pinned rounding order.
- **18 validations** (priority-ordered: auth → existence → state → OCC → safety → referential → constraint → temporal → fiscal), **60 endpoints** (incl. `/_clock/set_current_utc` with the mandatory `2026-01-01T00:00:00Z` default), **18 error codes**, **4 RBAC roles** (PracticeAdmin/FrontDesk opaque; Therapist/Client entity_backed with ownership checks), **1 concurrency rule** (OCC on `Table.version` for create-with-supersede booking).

**Difficulty design:** all 9 Difficulty Rules with exactly 2 instances each = **18 instances**, each grounded in declared scaffold elements with pre-computed literal assertions.

**Corner design:** **41 active + 6 excluded stubs** across all 9 claim-extraction taxonomy sections.

**Validation:** `scaffold_lint.py` → `VERDICT: clean lint` (610 calls scanned, all FK reverse-reachability satisfied). Fixed during review: stale OCC table-version reuse across multi-booking chains, check-in-window timing trap, dead `service_pricing` overflow branch, made `Superbill.VOID` enum reachable via dedicated void endpoint + state machine.

## Step 3: Copy INSTRUCTION.md — 2026-06-24T03:16:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0479_massage_therapy/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-24T03:20:00.000Z

Generated `workspace/PRD.md` (~302 lines, 50 KB). Confirmed: did NOT read either design file (DIFFICULTY/CORNER); reads limited to SCAFFOLD.yaml.

**PRD structure:** 5 top-level sections (§1 Introduction, §2 Global Specifications [10 subsections], §3 Business Logic & Workflows [11 subsections], §4 Endpoint Definitions [60 endpoints], §5 Error Code Catalogue [18 errors]).

**Hard Contract reports (PASS):**
- Field coverage: 84/84 entity fields, 59/59 request bodies, all query/path params — PASS.
- Rule coverage: validations (global + booking gate order), 1 OCC concurrency rule, all state machine transitions (Appointment scheduling+settlement, Package, SoapNote, Intake, ConsentRecord, Superbill), 5 calculations (service_pricing, client_owed_resolution, no_show_fee_proration, tiered_commission, package_rollover) with pinned rounding orders, 18 error conditions, cascades, sibling-branch symmetry — PASS.
- Path purity (§3 only): 429 backtick tokens scanned, 0 path-like / method tokens — PASS.

## Step 7: Run tests and iterate — 2026-06-24T03:57:35.000Z

Owned the test-and-fix loop synchronously in the foreground (no background subagent). Parallel 8-round `prd-bench-local-run --isolation per-test-server` stability sweep each iteration (results.1.json .. results.8.json), union of failures across all 8 rounds.

**Iterations run:** 1 fix iteration (baseline sweep → fix → confirming sweep).

**Baseline sweep:** all 8 rounds reported passed=10 / total=77 (67 unique failing tests, consistent across rounds — no flakiness; two systematic upstream causes).

**Final sweep:** all 8 rounds passed=77 / total=77.

**Tests deleted:** NONE. Every failing test traced to a PRD-faithful rule; both root causes were test-side construction bugs, not PRD-silence or PRD-ambiguity. No STEP 1a/1b deletions.

**Fixes applied to `implementation/`:** NONE. The implementation was already PRD-faithful on both failure clusters (it correctly enforced the letters-only modality `code` of PRD §2.4, and correctly returned HTTP 201 on creation per PRD §4 preamble). No implementation change made; no PRD-required check weakened; no data seeded.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `create_modality_payload`: the `code` default was `f"SWED{n:04d}"[:8]`, which contains digits and is rejected by the PRD-faithful impl (`ERR_INVALID_REQUEST` "code must be 2-8 uppercase letters"). PRD §2.4 states a modality `code` is "two to eight **letters**". Added a bijective base-26 `_letters(n)` helper and changed the default to `("MOD" + _letters(n))[:8]` — unique, letters-only, ≤8 chars. This single upstream fixture bug had cascaded into 51 "Setup step failed with HTTP 422" failures (every fixture that stands up a modality, directly or via `bookable_scenario`).

**Fixes applied to `test_suite/`:**
- 49 `validate_success(api.create_<entity>(...))` call sites across 6 files (test_02 ×1, test_03 ×6, test_05 ×32, test_06 ×1, test_07 ×3, test_08 ×6) asserted the default `expected_status=200` on creation endpoints. PRD §4 preamble states "Creating a new resource returns HTTP 201". Added `expected_status=201` to each (matching the value already used by the call sites the generator had gotten right, e.g. test_07:75, test_05:250, test_08:138). Fixed via AST transform (only `api.create_*` first-arg calls lacking an existing `expected_status` keyword; re-parsed each file to confirm validity). This cluster accounted for the 16 "Expected 200, got 201" failures.

Both fixes make the tests MORE faithful to PRD prose (letters-only code per §2.4; 201-on-create per §4 preamble). No skip/xfail, no assertion downgrades, no implementation back-doors, no seeded data.

## Step 8: Finalize PRD — 2026-06-24T04:00:02.000Z

Done. PRD_FINALIZED.md is created and is byte-identical to PRD.md — zero edits, which is the correct outcome here.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 302 lines vs 302 lines, **0% delta (identical).**

**Changes:** ZERO. Both `<step_7_diff>` fixes are pure test-side construction bugs against rules the PRD already states verbatim and uniquely determines. Per the Method's explicit guidance ("do NOT manufacture edits to look productive"), no edit was warranted.

### Per-item analysis with pre-edit search log

**Item 1 — `test_helpers/factories.py` `create_modality_payload` code default (digits → letters-only):**
- (a) Subject: the modality `code` validation rule (allowed character set / length).
- (b) Impl paths enumerated & read: `routes/modalities.py:14` defines `CODE_RE = re.compile(r"^[A-Z]{2,8}$")`, enforced at `:25-26` with message "code must be 2-8 uppercase letters". Grepped all `code`-pattern usages across `routes/` `services/` `helpers.py`: the only validator is in `modalities.py`. Cross-checked `routes/therapists.py:126-136` (certification `modality_code`) — it does NOT re-validate the letter pattern; it only checks the code equals a non-archived modality's `code`, and `services/appointments.py:102` compares cert `modality_code == modality["code"]`. So the letters-only rule lives solely at the modality-creation site.
- Impl behavior matches **PRD §3.1 verbatim**: "a short uppercase `code` of two to eight letters that is unique across all modalities and immutable once set." PRD already uniquely determines this; the fixture's old `f"SWED{n:04d}"[:8]` default contained digits, which is a fixture bug, not PRD-silence.
- (c) Wording adjustment: none (no edit).

**Item 2 — 49 `test_suite/` call sites + factory fix relating to HTTP 201 on creation:**
- (a) Subject: HTTP status code returned by resource-creation endpoints.
- (b) Impl paths enumerated & read: grepped `status=201` across `routes/`+`services/` → 13 sites, all on `POST .../create_*` resource-creation handlers (modalities, plans, commission-tiers, superbills, appointments, soap-notes, packages, clients, intakes, consent-records, tables, therapists, certifications). Inspected route decorators in `routes/clients.py`, `routes/plans.py`, `routes/therapists.py` to confirm the 201 sites are creations and that state-changing actions (sign, revoke, wallet-adjustments, reset-commission, etc.) use `response.success`'s default `status=200` (`response.py:17`).
- Impl behavior matches **PRD §4 preamble verbatim**: "Creating a new resource returns HTTP 201 with the created resource in `data`; reads and state-changing actions that modify an existing resource return HTTP 200." PRD already uniquely determines this; the test suite's default `expected_status=200` was a test-side bug.
- (c) Wording adjustment: none (no edit).

Both fixes make the tests more faithful to PRD prose the PRD already pins. No implementation choice was left open by the PRD on either subject, so PRD_FINALIZED.md is correctly identical to PRD.md.

## Step 9: Complete PRD — 2026-06-24T04:08:01.000Z

Produced `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0479_massage_therapy/workspace/PRD_COMPLETED.md` by copying `PRD_FINALIZED.md` and applying 13 minimal in-paragraph edits. No sections added; no behavior invented.

**File metrics**
- Source `PRD_FINALIZED.md`: 302 lines, 50,015 chars.
- `PRD_COMPLETED.md`: 302 lines, 55,144 chars (char delta +5,129; line count unchanged — all edits are in-paragraph).

**Counts**: 12 ambiguity-pins, 1 mismatch-revision.

**Per-change list** (`section — action — type — what changed — impl ref`):
- §2.1 RBAC — insert — ambiguity — pinned that a non-owning Therapist/Client fetching a single appointment or SOAP note gets `ERR_NOT_FOUND` (404), while all other ownership-violating reads get `ERR_UNAUTHORIZED` (403) — routes/appointments.py:161-164, routes/soap_notes.py:104-107 vs routes/clients.py:71, packages.py:73, superbills.py:72.
- §2.3 Pagination — insert — ambiguity — pinned the secondary sort (insertion/creation order) when `created_at` ties, and the exact `has_more` formula — helpers.py:157, response.py:27.
- §2.5 Logical Clock — insert — ambiguity — pinned clock-set response shape `data: {"now": "<instant>"}` at HTTP 200 — routes/clock_route.py:20.
- §3.2 Onboarding (intake sign) — insert — ambiguity — pinned that the superseded prior ACTIVE intake's `version` is bumped — routes/clients.py:164-165.
- §3.4 Booking — insert — ambiguity — pinned initial appointment field values (`cancel_reason` null; `service_charge_cents`/`client_owed_cents`/`no_show_fee_cents`/`commission_credited_cents` = 0) and defined "non-terminal" precisely (SCHEDULED/CHECKED_IN/COMPLETED by `scheduling_status` only) — routes/appointments.py:98-117, services/appointments.py:17.
- §3.4 Overlap gates — insert — ambiguity — pinned buffer-on-both-ends + half-open overlap math and the gap-equal-to-buffer-is-allowed boundary for table overlap, and the half-open test for therapist overlap — services/appointments.py:117-156.
- §3.5 Check-in — insert — ambiguity — pinned the four condition error codes and their evaluation order (INVALID_STATE, INVALID_STATE, LICENSE_EXPIRED, CONSENT_REQUIRED) — routes/appointments.py:177-190.
- §3.5 SOAP create — insert — ambiguity — pinned narrative fields optional/default empty string, clears defaults to empty list, non-assigned-therapist → ERR_UNAUTHORIZED — routes/soap_notes.py:60-74, 57-58.
- §3.5 SOAP edit — insert — ambiguity — pinned check order (field-present → DRAFT-state → version-match) and partial-overwrite semantics — routes/soap_notes.py:120-136.
- §3.5 Completion — insert — ambiguity — pinned wrong-state and missing-note both → ERR_INVALID_STATE (state first), non-assigned therapist → ERR_NOT_FOUND — routes/appointments.py:206-216.
- §3.6 Cancellation — insert — ambiguity — pinned 1440-minute cutoff, late-cancel sets only `no_show_fee_cents` (not `client_owed_cents`), free cancel leaves `settlement_status` UNSETTLED, appointment version bumps but client version does not — routes/appointments.py:249-259.
- §3.7 Fee proration — insert — ambiguity — pinned lead-time computation (whole seconds truncated toward zero, divided by 60 as exact rational) — services/appointments.py:180-181.
- §3.9 Commission — insert — ambiguity — pinned commission = 0 when no non-archived tiers exist and when `service_charge_cents` <= 0 — services/appointments.py:228, 236, 255.
- §3.9 Void — **revise** — **mismatch** — corrected the contradictory "voiding a paid session voids any superbill" claim: PAID is not voidable (→ ERR_INVALID_STATE), `scheduling_status` unchanged, and the void path runs no superbill cascade at all — routes/appointments.py:423-435.
- §3.10 Membership cycle — insert — ambiguity — pinned `current_cycle_end` math (advance to next calendar month, year-rolls past December, land on `cycle_anchor_day`, preserve time-of-day, discard source day-of-month) — services/packages.py:9-22.

Tests were used only as auxiliary cross-reference (types.py/assertions.py/constants.py confirmed field shapes and enum sets); the implementation was the sole alignment authority.
