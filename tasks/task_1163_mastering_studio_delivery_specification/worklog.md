# Worklog — task_1163_mastering_studio_delivery_specification

## Step 1: Create task directory — 2026-08-11T06:23:00.000Z

Pre-assigned output folder `tasks/task_1163_mastering_studio_delivery_specification` with `workspace/` subdirectory already exists (index 1163 assigned by pipeline invoker; auto-index scan skipped per instructions). Step 1 treated as done.

## Step 2: Generate scaffold — 2026-08-11T06:52:00.000Z

Generated the scaffold artifacts for the mastering-studio task at `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/`.

**Verdict (from scaffold_lint.py, verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Counts:**
- Entities: 12 (Client, Engineer, PlatformProfile, Project, SessionSlot, SourceAsset, RevisionRound, Deliverable, QCReport, MetadataTag, ArchiveBundle, RushTierRule)
- State machines: 8 (Client, Project, SessionSlot, SourceAsset, RevisionRound, Deliverable, ArchiveBundle, MetadataTag)
- Calculations: 8 (quote_provisional, quote_final, compute_recall_fee, loudness_compliance_check, engineer_capacity_utilization, revision_billing_rounds, archive_recall_pricing_boundary, held_slot_ttl_expiry)
- Validations: 20 (priority 1-20 across auth, existence, state, business_safety, business_constraint, business_referential, business_fiscal, business_temporal)
- Endpoints: 73 (including `/_clock/set_current_utc` with the mandatory 2026-05-01T00:00:00Z default)
- Errors: 24
- Roles: 4 (Client [entity_backed:Client], Engineer [entity_backed:Engineer], QAChecker [opaque], StudioManager [opaque]) — segregation_of_duties model
- Concurrency rules (OCC): 2 (project-book-stale-client, round-submit-stale-project)
- Difficulty instances: 18 (9 rules × 2, all rule_ids present)
- Corner instances: 31 across 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting, consistency)

**File sizes:**
- SCAFFOLD.yaml: 75,299 bytes
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 87,770 bytes
- SCAFFOLD_CORNER_DESIGN.yaml: 66,759 bytes

**Harder-than-expert features built in:** dual-variant pricing (provisional vs final quote) on Project AND tiered/min-floor recall pricing on ArchiveBundle; tiered+threshold combinatorial formulas across modes (a) and (b); cyclic state machines on both Project (MASTERING↔REVISION) and Deliverable (BUILDING→QC_PENDING→QC_FAILED→BUILDING); two transitive cascades (client-suspend depth-3, round-reject depth-2); validation priority conflicts across (state, business_safety) and (business_constraint, business_fiscal); boundary checks on true-peak (<=) and HELD-slot expiry (strict <); cross-entity gates on (Project, Client) and (Deliverable, QCReport); two interval-overlap semantics (half-open slot-level and aggregate capacity); two compensating invariants (credit+price sum, engineer active_project_count); two OCC concurrency rules with strict `${var}` placeholder discipline throughout.

**Lint history:** 6 → 3 → 1 → 0 violations, all FK reverse-reachability fixes (added filtered-list and sub-resource GETs for Project, Deliverable, QCReport).

## Step 3: Copy shared files — 2026-08-11T06:53:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_1163_mastering_studio_delivery_specification/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T07:09:00.000Z

All contracts pass. The PRD is complete and verified.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/workspace/PRD.md`
**Size:** 52,164 bytes · **340 lines**

### Section list
- **§1. Introduction** (2 paragraphs: business context + segregation-of-duties/money/clock framing)
- **§2. Global Specifications** — 2.1 Role-Based Access Control (with per-role identity prose) · 2.2 API Response Structure (**verified byte-identical** to the canonical verbatim block) · 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, created_at ascending) · 2.4 Common Resource Properties · 2.5 Guard Evaluation Order (all 20 validation priorities in explicit ascending-order prose) · 2.6 Studio Time Discipline (30-min grid, half-open overlap, capacity formula, 15-minute hold TTL) · 2.7 Money, Credits, and Pricing Precision · 2.8 Loudness and Delivery Targets · 2.9 Optimistic Concurrency Control (both OCC rules) · 2.10 Nested Resource Retrieval · 2.11 The Logical Clock
- **§3. Business Logic & Workflows** — 3.1 Client Onboarding and Account Standing · 3.2 Roster, Platform Targets, and Rush Pricing Setup · 3.3 Booking a Mastering Session · 3.4 Holding and Confirming Studio Time · 3.5 Source Intake and Technical QC · 3.6 Mastering, Revision Rounds, and Client Approval · 3.7 Deliverable Builds, Quality Control, and Metadata · 3.8 Delivery, Archival, and Recall
- **§4. Endpoint Definitions** — 73 endpoints, 4-column table (Method / Path / Description / Authorized Role(s))
- **§5. Error Code Catalogue** — 24 errors, 2-column table (Error ID / HTTP Status Code)

### Hard-contract audit results
```
Field coverage check:
- entities[].fields: 73 required, 73 present, 0 missing
- endpoints[].request_body: 62 required, 62 present, 0 missing
- endpoints[].query_params/path_params: 2 required, 2 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed in §2.5 ascending-priority prose, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write framing + expected_client_version/expected_project_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed (from/to + preconditions + side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in prose (no pseudocode, no fuzzy wording), 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 73 endpoints + 20 scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 73 checked, all defaults/initials/constraints reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (terminate ×2, cancel ×3, recall entry ×2, restore ×2, approve/reject, qc-pass/fail, hold release ×2, tag verify/mismatch), all equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 365
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 39 state values and 84 enum values appear verbatim; all 24 error IDs are mentioned in §2/§3 narrative; no fuzzy/approximating words anywhere; no operator-syntax leaks in §3. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened, and no sibling task directories were touched.

## Step 5: Generate unit tests — 2026-08-11T07:32:00.000Z

Generation complete. Summary:

## test_helpers/ (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/test_helpers/`)
`__init__.py` (barrel), `types.py` (12 entity TypedDicts + 15 enums, all common_fields:true), `api_client.py` (ApiClient(GenericApiClient), 60 methods — one per PRD §4 endpoint), `api_errors.py` (24 error IDs + status map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + credit invariant), `factories.py` (input-field-only payload factories), `constants.py` (HELD_TTL 15, LUFS_TOLERANCE 0.5, BP scale 10000, recall fee tiers/floor), `test_users.py` (opaque manager/QA constants + mandatory per-instance `make_client_headers`/`make_engineer_headers` builders), `fixtures.py` (tiered composites: booked → mastering → revision → approved → ready/verified deliverable → delivering → delivered → archived → recalled; identity-threaded throughout).

## test_suite/ (9 files)
`conftest.py` + `test_01_pricing_quotes.py` (4), `test_02_archive_recall.py` (5), `test_03_revision_rounds.py` (6), `test_04_deliverable_qc.py` (10), `test_05_booking_slots.py` (11), `test_06_client_lifecycle.py` (8), `test_07_entities_envelope_pagination.py` (12), `test_08_security_rbac_constraints.py` (5).

## Counts
- **Total tests: 61** — Queue A (Difficulty): **34** (17 instances × 2 each); Queue B (Corner): **27** (26 instances × 1, plus a boundary-complement second test for `loudness_check_precision_half_lu_tolerance`).

## Skipped instances (2, non-stub)
- **Difficulty/resource_temporal_overlap/project_book_capacity_aggregate_overlap** — asserted `ERR_CAPACITY_EXCEEDED` is not uniquely derivable: PRD §2.6's window-scoped capacity formula counts only slot minutes intersecting [11:00,12:00); the adjacent 10:00–11:00 slot contributes 0, leaving remaining=60 ≥ 60, so a faithful PRD-only implementation would *succeed* the booking.
- **Corner/validations/cross_entity_engineer_must_be_available_for_intake** — PRD §2.5 explicitly scopes the `ERR_ENTITY_NOT_ACTIVE` guard to booking and hold-confirmation ("booking and hold-confirmation are the two guarded operations"); §3.5 states the intake AVAILABLE requirement but names no error_id, so the asserted 422 is not uniquely derived.
- 4 `excluded_because:` stubs not translated; all cross-references verified to resolve.

## Notable translation decisions
- **Deliver-before-deliverable ordering**: every full-lifecycle `setup_api_calls` chain calls `deliver` before any deliverable exists, which violates the PRD §3.8 precondition ("requires at least one deliverable produced for the project's current revision round to have reached `VERIFIED`"). Fixtures use the PRD-consistent order (approve → deliverable to VERIFIED → deliver → finalize → archive); all asserted literals are unchanged. Where project state was incidental (deliverable rebuild/QC-gate instances), setups stop at APPROVED.
- **`archive_recall_fee_tiered_vs_min_floor` credit seed**: the instance's 50000-cent seed cannot cover its own 80000-cent approval debit; fixture seeds 500000 so the asserted recall fee (1000) is reachable. No asserted value changed.
- **Terminal-state 409 ambiguity**: PRD §2.5 assigns `ERR_ALREADY_TERMINAL` to terminal entities and `ERR_INVALID_STATE` to non-terminal state misses (plus `ERR_NO_ACTIVE_ROUND` for rounds) — three tests asserting the corner index's literal `ERR_INVALID_STATE` on terminal resources use `validate_error_is_one_of` (all candidates PRD-named, all 409) instead of a single contested error_id.
- **Round-submit OCC capture**: chains capture `expected_project_version` from the reject response (a RevisionRound, not the Project); fixtures re-GET the project version before each submit.

## Stage-2 audit verdict
PASS — py_compile clean on all 18 files; `import test_helpers` clean; 61/61 docstrings end with exactly one verbatim `Design:` tag resolving to a real instance; every difficulty instance has exactly 2 tests; every non-stub corner instance has ≥1; all 66 quoted PRD citations survive whitespace-normalized grep of PRD.md (plus manual check of the nested-quote envelope citation); no skip/xfail markers anywhere.

## Step 6: Generate implementation — 2026-08-11T07:32:00.000Z

Done. The implementation is complete and verified.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/workspace/implementation/`

**File list (26 files, 88,313 bytes total):**

| File | Bytes | Role |
|---|---|---|
| `start.sh` | 396 | Guarded pip install (`python3 -c "import flask"` check), `exec python3 app.py`, executable |
| `requirements.txt` | 11 | flask>=3.0 |
| `app.py` | 1,419 | Entry point, error handlers, GET-request expiry sweep, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 2,094 | In-memory dict stores (12 entities), logical clock (default 2026-05-01T00:00:00Z, never wall-clock), UUID/ms-ISO-8601/version helpers |
| `errors.py` | 2,286 | All 24 error IDs from the catalog with correct HTTP statuses |
| `response.py` | 1,158 | Exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists |
| `middleware.py` | 5,742 | `X-User-ID`/`X-User-Role` auth, role checks, typed field validators, pagination (limit 1–100 default 10, offset), terminal-vs-invalid state guard, owner/assignee checks |
| `services/pricing.py` | 2,683 | quote_provisional / quote_final (Decimal, round-half-up at final step only, current engineer rate, extra rounds, breach surcharges), tiered recall fee with $10 floor |
| `services/capacity.py` | 2,792 | Half-open slot overlap, forward-looking capacity, engineer selector (ERR_SLOT_CONFLICT priority 7 before ERR_CAPACITY_EXCEEDED 8) |
| `services/loudness.py` | 861 | 4-condition compliance, 1-decimal-place quantization, 0.5 LU tolerance |
| `services/sweep.py` | 1,599 | Lazy expiry (HELD→RELEASED at `now >= held_expires_at`; OPEN→EXPIRED at `now > deadline_at` + quote_final fold-in) — runs on GET reads only, so write endpoints still return ERR_HOLD_EXPIRED (410) / ERR_SLA_BREACH (422) |
| `routes/` (13 modules) | ~57,000 | One module per resource group |

**Endpoints: 73 registered vs 73 declared** — exact match (orchestrator-verified: 73 (method,path) pairs in SCAFFOLD.yaml == 73 registered in routes/, zero missing, zero extra).

**Verification:**
- `py_compile`: all 20 `.py` files pass.
- Boot smoke: `PORT=17393 bash start.sh` booted in foreground; unauthenticated GET → 401 `ERR_UNAUTHENTICATED`; client create → 201 PROSPECT; list → paginated envelope; default logical clock confirmed at `2026-05-01T00:00:00.000Z`.
- Full lifecycle smoke passed: project create → activate → OCC rejection (412 on stale `expected_client_version`) → book (quote 24000 = 2h × 12000¢ × 1.0) → intake → asset QC → mastering → round submit (OCC) → approve (final 24000, credit 1000000→976000) → deliverable READY→EMBEDDED→VERIFIED → deliver → archive → recall (5 GiB COLD = 10000¢) → restore → resume to MASTERING.

**Key fidelity decisions:** no seeding anywhere (stores empty at boot, only comment mentions it); client version increments on book per endpoint side-effects; derived-field writes bump `version` per PRD §2.4; ERR_ALREADY_TERMINAL only for states with no outgoing transitions (so EXPIRED rounds reject submit with 409, FAILED assets accept waive, ARCHIVED projects accept recall); recall reachable via both project and bundle paths; suspend cascade releases HELD slots and cancels DRAFT/BOOKED/INTAKE projects with engineer count decrements.

## Step 7: Run tests and iterate — 2026-08-11T07:39:00.000Z

All 8 rounds pass 61/61. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep → fix → verification sweep, 8/8 rounds green).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** 1
  - `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/test_helpers/fixtures.py`, fixture `make_deliverable`: the helper forwarded both explicit per-field keyword arguments (`integrated_lufs=profile[...]`, `true_peak_dbtp=profile[...]`, etc.) and `**overrides` into `create_deliverable_payload`, so any test overriding one of those measured fields (e.g. `make_deliverable(ctx, true_peak_dbtp=-1.0)`) crashed with `TypeError: got multiple values for keyword argument`. Fixed by merging profile defaults with overrides into a single dict (overrides win) before calling the factory. This was a pure test-fixture bug — the tests and implementation were both PRD-faithful (PRD §2.8 boundary checks on `true_peak_dbtp` ceiling and `integrated_lufs` ±0.5 LU tolerance).

- **Fixes applied to `implementation/`:** none — the implementation was already correct; all 4 failing tests failed in test setup, before any request reached the server.

- **Final state:** 61/61 passed in each of rounds 1–8 (no flakiness observed). Orchestrator-verified on disk: 8 result files, all `passed == total == 61`, failed=0, errors=0.

## Step 8: Finalize PRD — 2026-08-11T07:42:00.000Z

PRD_FINALIZED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/workspace/PRD_FINALIZED.md` — byte-identical to PRD.md (verified: same md5 `f3f7f3a47cd6008c8e2b8f58a87f9fbb`).

## Summary

**Line counts / delta:** PRD.md 340 lines; PRD_FINALIZED.md 340 lines; 0 lines changed, 0.0% delta.

**Changes:** none. The step_7_diff contains exactly one item, and it is a pure test-fixture bug with no PRD implication:

- **test_helpers/fixtures.py `make_deliverable` (test-fixture bug, no PRD edit needed)** — The buggy helper forwarded explicit per-field kwargs plus `**overrides` into `create_deliverable_payload`, so overriding a measured field (e.g. `true_peak_dbtp=-1.0`) raised `TypeError` in test setup, before any request reached the server. The on-disk fixture is now the fixed version (profile defaults merged with overrides into one dict, overrides win; `fixtures.py:236-244`). The behavior exercised by the four crashing tests is already uniquely determined by PRD §2.8 verbatim — the test docstrings quote the PRD sentences directly (`test_04_deliverable_qc.py:92-168`): true-peak must not exceed the profile ceiling, and |measured − target| ≤ 0.5 LU at one decimal place. The implementation matches the PRD exactly: `services/loudness.py:15-21` computes `abs(_q1(d.integrated_lufs) − _q1(p.integrated_lufs)) ≤ 0.5`, `_q1(d.true_peak_dbtp) ≤ _q1(p.true_peak_dbtp)`, `_q1(d.loudness_range_lu) ≤ _q1(p.loudness_range_lu)`, and exact `sample_rate_hz`/`bit_depth` equality, with `_q1` quantizing to 0.1 ROUND_HALF_UP (matching §2.8's "carried at one decimal place"); it is invoked only from the deliverable qc-pass path at `routes/deliverables.py:138`, consistent with §3.7's verdict rule. The five measured fields the fixture parameterizes are all PRD-declared request payload fields (§3.7). No implementation change was made in Step 7 and no PRD silence or mismatch exists at this site — pinning anything further (e.g. fixture default values) would invent behavior the PRD does not need and the impl does not exhibit.

**Per-edit pre-edit search log:** no edits were committed, so no pre-edit searches were triggered by edits. For completeness, the no-edit determination for the single diff item was reached by: (a) subject — deliverable loudness/format compliance inputs (`integrated_lufs`, `true_peak_dbtp`, `loudness_range_lu`, `sample_rate_hz`, `bit_depth`); (b) paths enumerated and read — `implementation/services/loudness.py` (whole file), `implementation/routes/deliverables.py:44-59,138` (payload parsing + sole compliance callsite), `implementation/routes/platform_profiles.py:34-55` (profile range validation), `test_helpers/fixtures.py` (whole file), `test_helpers/factories.py:99-110` (`create_deliverable_payload`), all 7 `make_deliverable(` callsites in `test_suite/test_04_deliverable_qc.py`, and `results.1.json`/`results.8.json` (61/61 passed, confirming the step_7_diff final state); (c) n/a — no wording proposed.

A fresh implementer reading PRD_FINALIZED.md (== PRD.md) already has §2.8 and §3.7 determining every behavior Step 7 touched, so no patch was warranted.

## Step 9: Complete PRD — 2026-08-11T07:58:00.000Z

PRD_COMPLETED.md is complete and verified. Summary:

**File stats**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/workspace/PRD_FINALIZED.md` — 340 lines, 52,164 chars
- Output: `/home/ubuntu/github/CodingPRD/tasks/task_1163_mastering_studio_delivery_specification/workspace/PRD_COMPLETED.md` — 340 lines, 58,145 chars
- Char-delta: +5,981 (zero lines added/removed; 36 paragraph-lines revised inline, no new sections/paragraphs)

**Counts: 35 ambiguity-pins, 4 mismatch-revisions (39 changes total)**

**Ambiguity-pins (35):**
- §2.1 — insert — ambiguity — client may fetch only own Client record; Client-role list endpoints enforce ownership as visibility scoping (slots with no project stay visible to all clients) — middleware.py:158-167, projects.py:144-145, session_slots.py:78-85, deliverables.py:91-93, qc_reports.py:87-89, archive_bundles.py:25-27
- §2.3 — insert — ambiguity — non-integer/out-of-range limit (1–100) or negative offset → ERR_INVALID_REQUEST 400 — middleware.py:106-125
- §2.3 — insert — ambiguity — same-instant records ordered by insertion sequence — db.py:78-100
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — db.py:78-87
- §2.5 — insert — ambiguity — unparseable ISO-8601 timestamp field → ERR_INVALID_FORMAT 400 — middleware.py:99-103
- §2.5 — insert — ambiguity — terminal-state enumeration per entity (drives ERR_ALREADY_TERMINAL vs ERR_INVALID_STATE); ownership/assignment checks run after path existence (priority 3), before state admissibility (priority 5) — middleware.py:19-29,146-155, projects.py:95-100
- §2.6 — insert — ambiguity — expired HELD slots count as released for overlap/capacity arithmetic — services/sweep.py:26-32, services/capacity.py:32-46
- §2.6 — revise — ambiguity — expiry check runs on every GET request, sweeping all slots and rounds system-wide — app.py:18-23, services/sweep.py:35-48
- §2.8 — insert — ambiguity — required_sample_rate_hz must be >0; any profile bound violation → ERR_INVALID_REQUEST 400; duplicate platform_code → ERR_INVALID_REQUEST at HTTP 409 — platform_profiles.py:21-50
- §3.1 — insert — ambiguity — duplicate contact_email → ERR_INVALID_REQUEST at HTTP 409 — clients.py:27-29
- §3.1 — insert — ambiguity — first activation with no project → ERR_INVALID_STATE 409 — clients.py:72-76
- §3.1 — insert — ambiguity — termination with in-flight projects → ERR_INVALID_STATE 409 — clients.py:116-120
- §3.1 — insert — ambiguity — negative credit adjustment below zero → ERR_INSUFFICIENT_CREDIT 402; success returns updated Client with 201 — clients.py:134-140
- §3.2 — insert — ambiguity — hourly_rate_cents ≤0 / capacity <0 → ERR_INVALID_REQUEST 400 — engineers.py:25-29
- §3.2 — insert — ambiguity — engineer changing another's availability → ERR_ENGINEER_NOT_ASSIGNED 403 — engineers.py:74-76
- §3.2 — insert — ambiguity — duplicate tier → ERR_INVALID_REQUEST at 409; sla_hours ≤0 → ERR_INVALID_REQUEST 400; default rule (10000bp/24h/0/0/0) when no rule row exists — rush_tier_rules.py:23-30, services/pricing.py:22-39
- §3.3 — insert — ambiguity — duration violating multiple-of-30/[60,480] → ERR_INVALID_REQUEST 400; new project's quoted/final price cents start at 0 — projects.py:102-104,128-129
- §3.3 — insert — ambiguity — booking-created BOOKED slot carries held_expires_at null — projects.py:192-200
- §3.4 — insert — ambiguity — slot end not strictly after start → ERR_INVALID_REQUEST 400; client project_id ownership and read-visibility rules — session_slots.py:40-49,78-85
- §3.5 — insert — ambiguity — engineer-not-AVAILABLE on either intake path → ERR_ENTITY_NOT_ACTIVE 422 — projects.py:230-232, source_assets.py:54-57
- §3.5 — insert — ambiguity — bad sha256/duration≤0/channels∉{1,2,6,8} → ERR_INVALID_REQUEST 400; uploads only in BOOKED/INTAKE; availability check fires after checksum-uniqueness guard — source_assets.py:34-57
- §3.5 — insert — ambiguity — qc_failure_reason required on qc-fail — source_assets.py:139-140
- §3.5 — insert — ambiguity — qc-complete vacuously allowed with zero assets; any asset not PASSED/WAIVED → ERR_INVALID_STATE 409 — projects.py:246-249
- §3.6 — insert — ambiguity — submit returns the updated round — rounds.py:89
- §3.6 — insert — ambiguity — expiry sweep recomputes/writes project final_price_cents and bumps project version at the read-time sweep — services/sweep.py:41-48
- §3.6 — insert — ambiguity — approve/reject return the updated round — rounds.py:116,139
- §3.7 — insert — ambiguity — deliverable creation requires only round existence under the project (no status consulted; unknown/cross-project round → 404) — deliverables.py:49-52
- §3.7 — insert — ambiguity — QC report recording: no engineer-assignment match required; sets deliverable qc_report_id (version bump); allowed in any deliverable status; `passed` filter is case-insensitive true/false — qc_reports.py:38-65, middleware.py:128-136
- §3.7 — insert — ambiguity — qc-fail with no failing report → ERR_QC_FAILED 422 — deliverables.py:152-154
- §3.7 — insert — ambiguity — ISRC collision per project+kind → ERR_INVALID_REQUEST at 409, ignoring REVOKED tags — deliverables.py:196-202
- §3.7 — insert — ambiguity — verify-metadata acts on the most recently created tag; none EMBEDDED → ERR_INVALID_STATE 409 — deliverables.py:224-229
- §3.7 — insert — ambiguity — "newer" superseding deliverable = created later, any status — deliverables.py:245-250
- §3.8 — insert — ambiguity — deliver/finalize-delivery precondition failures → ERR_INVALID_STATE 409 — projects.py:281-283,302-304
- §3.8 — insert — ambiguity — negative archive_size_bytes → ERR_INVALID_REQUEST 400; archive response carries the created ArchiveBundle — projects.py:318-319,336
- §3.8 — insert — ambiguity — recall on bundle PENDING/RESTORING → ERR_INVALID_STATE 409, RESTORED/FAILED → ERR_ALREADY_TERMINAL 409; project-path recall with no bundle → ERR_NOT_FOUND 404; response carries the updated bundle — projects.py:339-346,372-376, archive_bundles.py:51-61
- §3.8 — insert — ambiguity — resume-from-recall: bundle FAILED → ERR_ALREADY_TERMINAL 409, otherwise not-RESTORED → ERR_INVALID_STATE 409 — projects.py:389-393

**Mismatch-revisions (4):**
- §3.3 — revise — mismatch — engineer selector rewritten: scans AVAILABLE engineers in onboarding order, picks first with no overlap and sufficient capacity; on total failure raises ERR_SLOT_CONFLICT if any AVAILABLE engineer was disqualified by overlap, else ERR_CAPACITY_EXCEEDED — services/capacity.py:56-74
- §3.4 — revise — mismatch — slot `project_id` is fixed at creation and never reassigned (booking a project creates a fresh BOOKED slot rather than attaching an existing hold) — session_slots.py:34,60-67, projects.py:192-201
- §3.7 — revise — mismatch — MetadataTag is created already in EMBEDDED status; its DRAFT state is never persisted — deliverables.py:203-211
- §3.8 — revise — mismatch — recall fee: a zero-byte archive bills zero gigabytes before the 1,000-cent floor (PRD said "anything under a gigabyte still bills one") — services/pricing.py:77-80
