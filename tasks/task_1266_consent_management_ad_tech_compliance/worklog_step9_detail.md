
## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-08-12T00:00:00.000Z

**Source vs target:** workspace/PRD_FINALIZED.md (314 lines, 41983 chars) → workspace/PRD_COMPLETED.md (314 lines, 44106 chars). Char-delta: +2123 chars. Line-delta: 0 (all edits are in-paragraph inserts/revisions).

**Counts:** ambiguity-pins: 7; mismatch-revisions: 0.

**Changes (one bullet per edit):**

- §2.3 Pagination — revise — ambiguity — replaced "minimum of 1 and maximum of 100" phrasing (ambiguous between reject and clamp) with explicit clamping semantics: limit<1→1, limit>100→100, offset<0→0; non-integer values rejected with ERR_INVALID_REQUEST — implementation/response.py:84-85, implementation/services/consent.py:145-150.
- §3.1 Policies — revise — ambiguity — replaced "While ACTIVE, a policy's retention_days may be amended" with explicit permission for DRAFT and ACTIVE amendment, and pinned that any PUT on a RETIRED policy (status or retention-only) is rejected with ERR_POLICY_INVALID_TRANSITION — implementation/routes/policies.py:121-139.
- §3.3 Tag rules — insert — ambiguity — added sentence pinning that (banner_config_id, purpose_category) uniqueness is enforced across all tag-rule statuses (ENABLED, DISABLED, RETIRED all occupy the pair) — implementation/routes/tag_rules.py:67-76 (loop has no status filter).
- §3.5 Consent records — insert — ambiguity — added sentence pinning that a NECESSARY grant creates a persisted ConsentRecord like any other purpose, subject to the same gates and incrementing granted_purpose_count while GRANTED — implementation/routes/consent.py:106-155 (record created unconditionally; _apply_grant_gates runs for all purposes including NECESSARY).
- §3.5 Consent preview — insert — ambiguity — added sentence pinning the waterfall's policy selection: the ACTIVE policy whose coverage window contains the clock is consulted for gpc_honored and banner_regime; when none covers, the earliest-created ACTIVE policy of the jurisdiction is the fallback; when no ACTIVE policy exists the regime-default step yields DENIED_BY_DEFAULT — implementation/services/consent.py:308-317 (effective_decision policy selection).
- §3.7 Vendor risk — insert — ambiguity — added sentence pinning that risk-score recomputation does not bump vendor version/updated_at — only direct vendor mutations (registration, approval, suspension) advance them — implementation/services/audit.py:9-31 (recompute_vendor_risk never calls touch on the vendor).
- §3.8 Sweeps (deadline / escalation) — insert — ambiguity (two related pins in adjacent paragraphs) — (a) respond attempted on an already-lazy-escalated sweep whose deadline has passed fails with ERR_SWEEP_DEADLINE_PASSED, not ERR_SWEEP_INVALID_STATE — implementation/routes/sweeps.py:161-168; (b) the posture-flip version bump fires only on an actual NORMAL→FROZEN flip — a second sweep escalating while the property is already FROZEN does not advance property version/updated_at — implementation/services/sweep.py:58-60 (guarded by `if prop.get("posture") != "FROZEN"`).

**Judgment-call checks explicitly verified (from the task brief):**
- Duplicate GET /v1/vendors/{id}/tracker-findings route: registered twice (implementation/routes/vendors.py:153 and implementation/routes/scans.py:257) with byte-identical filter+pagination behavior. §4 lists it once. No PRD change needed.
- Out-of-range limit/offset clamping, tag-rule uniqueness across all statuses, policy RETIRED rejection, consent-preview policy selection with earliest-created fallback, NECESSARY grants create records, risk-score recompute does not touch vendor version — all pinned above.
- Role "Any" reads exclude Anonymous: already uniquely pinned by PRD §2.1 ("Anonymous ... may only register new visitor profiles" + "Any denotes that every authenticated role"); implementation/middleware.py:27 and services/consent.py:34 both build READ_ROLES by excluding Anonymous. No additional edit needed.
