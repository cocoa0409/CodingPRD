# Worklog — task_1553_university_technology_transfer_licensing

## Step 1: Create Task Directory — 2026-08-13T20:44:00.000Z

Task directory `tasks/task_1553_university_technology_transfer_licensing/` and `workspace/` pre-created and pre-assigned by pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T21:56:00.000Z

Scaffold generation complete for `task_1553_university_technology_transfer_licensing`. All three files are written and the lint is clean.

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/SCAFFOLD.yaml` — §1.0–§1.7 only
- `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    79
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1071

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
A separate self-consistency audit also passed: zero dangling `grounds:` refs, zero unreferenced error codes, zero instance-name collisions across both design files, no forbidden concurrency vocabulary.

## Counts
- **Entities: 14** — Department, Inventor, InventionDisclosure, DisclosureInventor (M2M junction), InventorshipDispute, PatentApplication, PatentCost, Startup, ConflictOfInterestPlan, LicenseAgreement, LicenseMilestone, RoyaltyReport, RoyaltyDistribution, FederalComplianceReport
- **State machines: 11** — including 4 cyclic/non-linear ones (license negotiation toggle + default/cure loop, patent prosecution office-action cycle, COI reject/revise loop, compliance report double loop into DRAFT)
- **Endpoints: 79** (incl. `POST /tlo/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- **Errors: 55**; **Roles: 9** (segregation-of-duties: ComplianceOfficer/Director and FinanceOfficer/Director pairs; Inventor is entity-backed)
- **Difficulty instances: 23** (every one of the 9 rules has ≥2; transitive_cascade/priority_pair/boundary have 3, cross_entity_state_dependency have 4)
- **Corner instances: 62 active + 4 excluded-because stubs** across 8 taxonomy sections

## Key design decisions (harder-than-expert calibration)
- **Dual-variant calcs on different domains**: royalty earned-only vs annual-minimum true-up (RoyaltyReport), and FIXED vs clamped ANTI_DILUTION equity (Startup).
- **Combinatorial formulas in different modes**: mode (a) distribution waterfall (nested `min`, funding-source and startup-linkage conditional pct branches); mode (b) inventor/department share splits with pinned floor-then-remainder-cent ordering (share_bp DESC, created_at ASC — never id).
- **Transitive cascades of depth 3/3/2**: license termination → report void → distribution cancel → cost-offset reversal; patent abandon → write-off → rollup recompute → review-flag threshold flip blocking new filings; distribution pay → report PAID → department pool ledger sync.
- **Validation priority conflicts on three distinct category pairs**: {state, fiscal}, {referential, constraint}, {state, safety} — each with dual-failure triggers and precomputed winners.
- **Boundary precision**: tier cap exactly-at vs exactly-over, share sum 9999 vs 10000bp, due_date `==` on-time vs `+1s` late, cure-deadline `<=` vs terminate `>`, write-off threshold 4999999 vs 5000000, upfront floor 499999 vs 500000.
- **Temporal overlap with different interval semantics**: COI plans half-open (adjacency allowed) vs exclusive licenses closed-interval (single shared day conflicts).
- **Compensating invariants on different quantities**: approve→cancel restores unreimbursed cost cents exactly (via recorded `cost_applications`); dispute→resolve→re-dispute→restore conserves the 10000bp share vector.
- **OCC on three parents** (disclosure finalize, license execute, distribution approve) with `recalculate`/`counter`/`dispute` as legitimate version-bumping supersede paths, all tests using `${var}`-captured versions.
- **Compliance gating**: Bayh-Dole-style ELECTION_OF_TITLE (due = min(statutory 730d, bar date − 30d)) gates NON_PROVISIONAL/PCT filings; COI coverage-of-clock gates startup-linked license execution and equity issuance.

## Step 3: Copy Shared Files — 2026-08-13T21:57:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1553_university_technology_transfer_licensing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T22:10:00.000Z

(First subagent invocation exited before writing the file; resumed via SendMessage and completed.)

All three contracts pass. The PRD is complete.

---

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/workspace/PRD.md` — 338 lines, ~7,125 words.

### Section structure
- **§1 Introduction** (2 paragraphs): frames the TTO domain from business-context and risk angles; names the `/tlo` mount and the logical-clock/segregation-of-duties pillars.
- **§2 Global Specifications** (10 subsections): 2.1 RBAC with per-role `identity:` translations (Inventor entity-backed; all others opaque); 2.2 fixed verbatim response-envelope block; 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 common properties + cents/basis-points/round-half-up conventions; 2.5 logical clock (default `2026-08-01T00:00:00Z`, activation/expiry sweep); 2.6 ordered 10-stage validation pipeline; 2.7 left-to-right nested retrieval; 2.8 OCC (three endpoints, `ERR_STALE_VERSION`/412); 2.9 prosecution-cost ledger and 5,000,000-cent write-off review threshold; 2.10 segregation of duties.
- **§3 Business Logic** (9 subsections, lifecycle-ordered): disclosure intake/inventorship → assessment gate → patent docket (3-hop abandon cascade) → startups/equity/COI (both equity variants with clamp reachability) → license negotiation/execution (5 ordered execute checks, fiscal floor last) → milestones/default/termination (3-hop cascade) → royalty reporting (tiered royalty + year-closing true-up) → distribution waterfall and both largest-remainder share splits → federal compliance reporting (180/730/365−30 due dates, strict lateness boundary).
- **§4 Endpoint table:** 79 rows, 4 columns each, matching all 79 scaffold endpoints.
- **§5 Error catalogue:** 55 rows, 2 columns, matching all 55 scaffold errors.

### Coverage audit results
- **Contract 1 (Field-Name Coverage):** 115/115 required names present in backticks; 0 missing (after repair pass adding the 12 path-param names, `college_name`, `license_id`, `patent_application_id`, `royalty_report_id`, `status`). PASS.
- **Contract 2 (Rule Coverage):** 49/49 targeted rule checks pass — all 10 validation priorities with ordering prose, all 3 OCC rules (endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412), all state transitions with preconditions/error IDs, all 8 calculations with pinned evaluation orders (per-portion round-then-sum, floor-then-largest-remainder, floor-before-clamp, strict lateness boundary, inclusive tier cap), all side-effect cascades (abandon 3-hop, terminate 3-hop, pay ledger sync, agency-reject clearing), sibling-branch symmetry across decision/grant/cancel/dispute branches. PASS.
- **Contract 3 (§3 Path Purity):** 506 backtick tokens in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.

### Scaffold-to-PRD adjudications
- `ERR_REPORT_NOT_ACCEPTABLE` is intentionally overloaded in the scaffold (accept gate + distribution-create gate); the PRD preserves this single error ID for both conditions, stated in §3.7 and §3.8 respectively.
- The scaffold's `ERR_DISCLOSURE_INVALID_STATE` covers both state-machine violations and the `PATENT_PURSUED` prerequisite for patent/startup/license creation; the PRD expresses both usages with the same error ID (§3.2, §3.3).
- Monetary constants rendered in cents (e.g., "5,000,000 cents") with a parenthetical dollar gloss only where it adds context, keeping integer-cents reconstruction exact; the tier cap's inclusive boundary and the anti-dilution clamp reachability notes are stated in prose without numeric leakage beyond the scaffold's own constants.
- `late_flag` boundary stated as strictly-after (on-time when equal), matching the scaffold's `>` semantics.
- §2.2 emitted byte-identically from the canonical source file, including `req_RANDOMALPHANUM123456` and `"data": { }`.

## Step 5: Generate Unit Tests — 2026-08-13T22:40:00.000Z

(RESUME RUN note: the prior run was killed after Steps 5/6 generation completed but before their worklog entries were written. On resume, the orchestrator verified the artifacts rather than regenerating them.)

Artifact verification (2026-08-13T23:05Z): `test_helpers/` contains all 9 required files (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`); `test_suite/` contains `conftest.py` + 5 test files. All Python files parse cleanly with `ast.parse` (no truncation). Design-tag audit: 68 test functions, 68 `Design: ` docstring tags (test_01: 21/21, test_02: 16/16, test_03: 12/12, test_04: 11/11, test_05: 8/8) — every test tagged. Artifacts judged complete; reused as-is.

## Step 6: Generate Implementation — 2026-08-13T22:35:00.000Z

(RESUME RUN note: same killed-run recovery as Step 5 above.)

Artifact verification (2026-08-13T23:05Z): `workspace/implementation/` contains `app.py`, `start.sh` (executable launcher, reads `$PORT`, foreground `exec python3 app.py`, conditional pip install), `requirements.txt` (flask>=3.0), `serializers.py`, `services.py`, `store.py`, `util.py`, and `routes/` package (`__init__.py`, `admin.py`, `compliance.py`, `disclosures.py`, `licenses.py`, `patents.py`, `royalties.py`, `startups.py`). All Python files parse cleanly (no truncation). Artifacts judged complete; reused as-is.

## Step 7: Run Tests and Iterate — 2026-08-13T23:25:00.000Z

## Summary

**Iterations run:** 2 (initial sweep + 1 fix-and-resweep)

**Tests deleted:** None — every failing test traced to verbatim PRD coverage and the fix belonged to the test fixture or implementation, not the assertion.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/test_helpers/fixtures.py` — added a new `add_cost(application_id, amount_cents, cost_type, incurred_date)` helper that wraps `api_client.add_cost` with `_ok` validation, used by `test_02_assessment_and_patent_docket.py`. The previous test suite import (`from test_helpers import add_cost`) referenced a symbol that was never exported, causing module-level `ImportError` and a full-file collection failure.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/test_suite/test_05_milestones_default_termination.py` (`test_cure_deadline_and_terminate_boundaries`) — removed spurious `title="A"` / `title="B"` kwargs from two `setup_defaulted_license()` calls. The helper forwarded them into `create_license_payload`, producing `ERR_INVALID_REQUEST: Unknown payload field(s): title` during setup. The titles were cosmetic labels with no semantic role in the test (the two defaulted licenses are independently constructed anyway).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/workspace/implementation/store.py` — changed `new_id()` from `uuid.uuid4().hex` to `str(uuid.uuid4())`. The PRD requires "a server-minted UUID with no type prefix"; canonical UUID rendering includes dashes (8-4-4-4-12). The test_helpers `is_valid_uuid` correctly requires the canonical form, so the previous dashless 32-char hex failed the bare-UUID assertion.
- `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/workspace/implementation/routes/disclosures.py` (`finalize_inventorship`) — moved the `expected_disclosure_version` OCC check ahead of the `INVENTORSHIP_REVIEW` state check. PRD §2.8 explicitly names the scenario "if a dispute cycle has advanced the version since the officer last read the disclosure, the finalize is rejected with ERR_STALE_VERSION"; a dispute also moves the disclosure to `INVENTORSHIP_DISPUTED`, so PRD's named outcome can only fire when OCC runs before state-machine legality. (`ERR_STALE_VERSION` is HTTP 412, not a §5 409, so it is not bound by §2.6 stage 5.)

**Result:** All 8 parallel rounds pass 68/68.

## Step 8: Finalize PRD — 2026-08-13T23:35:00.000Z

Step 8 complete. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/workspace/PRD_FINALIZED.md`.

## Line counts / delta
- `PRD.md`: 338 lines; `PRD_FINALIZED.md`: 338 lines — 0% line-count delta (2 lines revised in place; no sections added or removed).

## Changes (2 edits, each traced to a `<step_7_diff>` implementation fix)

- **§2.4 (line 74) — revise —** resource `id` now pinned as "a server-minted UUID rendered in its canonical dashed 8-4-4-4-12 hexadecimal form, such as `550e8400-e29b-41d4-a716-446655440000`, with no type prefix" (was: "a server-minted UUID with no type prefix", which admitted the dashless-hex reading the original implementer took) — `workspace/implementation/store.py:39-40` (`new_id()` returns `str(uuid.uuid4())`).
- **§3.1 (line 114) — revise —** finalize-inventorship OCC sentence now pins evaluation order: "this version check is evaluated before the finalizability conditions above, so if a dispute cycle has advanced the version ... the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412) even though the dispute has also moved the disclosure out of `INVENTORSHIP_REVIEW`" — `workspace/implementation/routes/disclosures.py:160-167` (OCC check at line 160 precedes the state/roster check at line 164).

Items needing no edit: the `test_helpers/fixtures.py` `add_cost` addition was a missing-export fixture bug (§3.3 already pins the cost payload; verified against `routes/patents.py:143-162`), and the `test_05` `title=` kwarg removal was a test bug (§2.6 already pins unknown-payload-field rejection as `ERR_INVALID_REQUEST`).

## Per-edit pre-edit search log

**Edit 1 (UUID form)**
- (a) Subject: string format of system-managed resource `id` values.
- (b) Paths enumerated: `store.py:39-51` (`new_id()` sole mint site, applied by `create_record` to every collection record); `serializers.py` (all 15 serializer sites emit `d["id"]` verbatim — grep of `"id"` across serializers); `util.py:33` (`_request_id()` mints `req_`+20-alnum `api_request_id` — not a resource id, governed separately by §2.2); all path-id consumption is dict-key lookup (no format validation anywhere). Runner-side `is_valid_uuid` (`prd-bench-local-runner/.../testing/assertions.py:19-30`) requires the dashed 8-4-4-4-12 regex.
- (c) Adjustment: kept the sentence scoped to resource `id` (its existing scope) so the `req_`-prefixed `api_request_id` contract in §2.2 is untouched; "canonical dashed 8-4-4-4-12 hexadecimal form" is satisfied by `str(uuid.uuid4())` for every resource type.

**Edit 2 (finalize OCC ordering)**
- (a) Subject: evaluation order of `expected_disclosure_version` vs state/finalizability checks at finalize.
- (b) Paths enumerated: all three OCC sites — `disclosures.py:150-173` finalize (schema → OCC → state/roster → share-sum), `licenses.py:127-159` execute (schema → **state → OCC** → COI → overlap → floor), `royalties.py:184-203` approve (schema → **state → SoD → OCC**). Other disclosure-mutating endpoints (`record_assessment`, `record_decision`, `clear_cost_review`, `confirm_entry`, `dispute_entry`, `resolve_dispute`) carry no OCC token. Tests: `test_01_...:386-407` exercises exactly the dual-failure dispute scenario and asserts 412.
- (c) Adjustment: wording scoped explicitly to the finalize operation ("this version check is evaluated before the finalizability conditions above") — deliberately no universal claim in §2.8, because execute and approve intentionally run their state (and SoD) checks before OCC; §3.5's "five checks" (state legality in the preamble + OCC/COI/overlap/floor) and §3.8's "two guards" (SoD, then OCC) already match those impl orders, so they were left verbatim.

## Step 9: Complete PRD — 2026-08-14T00:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1553_university_technology_transfer_licensing/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (338 lines / 53,578 chars → 339 lines / 57,555 chars; **+1 line, +3,977 chars**). All changes are inline inserts/revisions; no new sections, no removed behavior.

Counts: **30 ambiguity-pins, 3 mismatch-revisions** (33 changes total).

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.2 — insert — ambiguity — framework-level errors in same envelope: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — implementation/app.py:22-32
- §2.3 — insert — ambiguity — limit/offset must be integers; non-integer or negative offset → `ERR_INVALID_REQUEST` — implementation/util.py:121-136
- §2.3 — insert — ambiguity — list sort ties broken by creation sequence; `has_more` = offset + returned < total_count — implementation/util.py:52,142
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock, not wall clock — implementation/store.py:46-47,56
- §2.5 — insert — ambiguity — clock target replaces current value unconditionally (no monotonicity check) — implementation/routes/admin.py:21
- §2.5 — insert — ambiguity — sweep response field names `current_utc`/`activated_license_ids`/`expired_license_ids`, creation-order lists, expiry test runs before activation — implementation/routes/admin.py:23-27; services.py:317-330
- §2.6 — insert — ambiguity — non-JSON-object body rejected; JSON `null` treated as absent — implementation/util.py:152-178
- §2.7 — insert — ambiguity — identifier existing under a different parent yields that resource's not-found error — implementation/routes/licenses.py:255-261
- §3.1 — insert — ambiguity — inventor provisioning requires existing `department_id`, else `ERR_DEPARTMENT_NOT_FOUND` — implementation/routes/admin.py:78-79
- §3.1 — insert — ambiguity — disclosure submitter `X-User-ID` must name a provisioned Inventor, checked after role auth, before body validation — implementation/routes/disclosures.py:47-49
- §3.1 — insert — ambiguity — roster-add inventor existence (`ERR_INVENTOR_NOT_FOUND`) checked after schema, before state gate — implementation/routes/disclosures.py:117-121
- §3.1 — insert — ambiguity — disputes allowed from `INVENTORSHIP_REVIEW` or `INVENTORSHIP_DISPUTED`, else `ERR_DISCLOSURE_INVALID_STATE` — implementation/routes/disclosures.py:276-278
- §3.1 — insert — ambiguity — `adjusted_shares` `share_bp` schema range 1–10000 — implementation/util.py:244
- §3.4 — insert — ambiguity — `coverage_end` ≤ `coverage_start` is `ERR_INVALID_REQUEST` — implementation/routes/startups.py:139-140
- §3.4 — insert — ambiguity — COI filing requires inventor to exist (`ERR_INVENTOR_NOT_FOUND`) — implementation/routes/startups.py:141-142
- §3.4 — insert — ambiguity — filing-time overlap check vs `SUBMITTED`/`APPROVED` plans → `ERR_COI_WINDOW_OVERLAP` — implementation/routes/startups.py:150-154
- §3.4 — insert — ambiguity — COI rejection requires `SUBMITTED`, else `ERR_COI_NOT_REVIEWABLE` — implementation/routes/startups.py:207-208
- §3.4 — insert — ambiguity — revision: omitted fields retain current values; resulting window validity re-checked — implementation/routes/startups.py:224-227
- §3.5 — revise — mismatch — dropped "startup on the same disclosure"; impl only checks startup exists (`ERR_STARTUP_NOT_FOUND`, after the state gate) and does not cross-check the startup's disclosure — implementation/routes/licenses.py:67-69
- §3.5 — insert — ambiguity — counter `expiration_date` must be strictly after current `effective_date`, else `ERR_INVALID_REQUEST` — implementation/routes/licenses.py:114-115
- §3.6 — insert — ambiguity — milestone attachment allowed in any license status — implementation/routes/licenses.py:220-237
- §3.7 — revise — mismatch — removed "Once a license is in force"; report submission is not gated on license status — implementation/routes/royalties.py:45-72
- §3.7 — insert — ambiguity — `earned_royalty_cents`/`true_up_cents`/`accepted_royalty_cents` null until acceptance — implementation/routes/royalties.py:67-69
- §3.7 — revise — mismatch — closing year = license year containing `period_start`; the straddling report's own earned figure counts only when `period_end` coincides exactly with the year boundary — implementation/services.py:126-139
- §3.8 — insert — ambiguity — remainder-distribution ties broken by creation sequence after `created_at` (both inventor and department splits) — implementation/services.py:157
- §3.8 — insert — ambiguity — `inventor_shares`/`department_shares` element shapes (`inventor_id`/`department_id` + `amount_cents`) and emission in distribution order — implementation/services.py:188-209
- §3.8 — insert — ambiguity — recalculate defined only from `CALCULATED`, else `ERR_DISTRIBUTION_NOT_APPROVABLE` — implementation/routes/royalties.py:169-171
- §3.8 — insert — ambiguity — approval application order adds creation-sequence tie-break; `cost_applications` entries are `cost_id`/`applied_cents` pairs — implementation/services.py:239,253
- §3.9 — insert — ambiguity — `due_date` required for `UTILIZATION_REPORT`/`EXTENSION_REQUEST` (absence is `ERR_INVALID_REQUEST`), ignored for derived types — implementation/routes/compliance.py:38-40; services.py:393-404
- §3.9 — insert — ambiguity — `ACCEPTED` agency outcome leaves any stored `rejection_reason` unchanged — implementation/routes/compliance.py:130-131
- §4 — insert — ambiguity — inventor list filter query param named `department_id` — implementation/routes/admin.py:93-95
- §4 — insert — ambiguity — disclosure list filters are `status` and `funding_source` query params — implementation/routes/disclosures.py:89-94
- §4 — insert — ambiguity — dispute list filter query param named `disclosure_id` — implementation/routes/disclosures.py:312-314

Key findings: the most substantive mismatch was the §3.7 true-up rule — the finalized PRD said the closing-year earnings sum includes "this report's just-computed earned figure" unconditionally, but the implementation (`services.py:134-135`) only counts the report's own figure when its `period_end` lands exactly on the closing year's boundary, so a straddling report's earned royalty is excluded from the year it closes. Also notable: impl enforces a COI window-overlap check at plan *filing* (not just approval/revision) that the PRD never mentioned, and the license-to-startup link is not constrained to the same disclosure despite the PRD's wording.
