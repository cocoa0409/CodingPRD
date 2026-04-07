import {
  UserRole,
  Journal,
  Manuscript,
  ReviewAssignment,
  ReviewerProfile,
  Review,
  ConflictOfInterest,
  Certification,
  JournalStatus,
  ManuscriptStatus,
  ReviewAssignmentStatus,
  ReviewStatus,
  AnonymityLevel,
  ConflictOfInterestType,
  CertificationName,
} from './types';
import { ApiHeadersBase } from './api-client';

export function buildUserHeaders(userId: string, userRole: UserRole): ApiHeadersBase {
  return {
    'X-User-ID': userId,
    'X-User-Role': userRole,
  };
}

export function createUnixTimestamp(daysFromNow: number): number {
  const now = new Date();
  now.setDate(now.getDate() + daysFromNow);
  return Math.floor(now.getTime() / 1000);
}

export function addDays(timestamp: number, days: number): number {
  const seconds = days * 24 * 60 * 60;
  return timestamp + seconds;
}

function isValidUUID(uuid: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  return uuidRegex.test(uuid);
}

function isValidISO8601(timestamp: string): boolean {
  const iso8601Regex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$/;
  return iso8601Regex.test(timestamp);
}

function isValidDate(date: string): boolean {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

export function assertJournal(journal: any): asserts journal is Journal {
  expect(journal).toBeDefined();
  expect(typeof journal).toBe('object');
  expect(isValidUUID(journal.id)).toBe(true);
  expect(typeof journal.journal_name).toBe('string');
  expect(Object.values(JournalStatus)).toContain(journal.status);
  expect(typeof journal.total_prestige).toBe('number');
  expect(typeof journal.prestige_balance).toBe('number');
  expect(typeof journal.desk_reject_risk_score).toBe('number');
  expect(isValidISO8601(journal.created_at)).toBe(true);
  expect(isValidISO8601(journal.updated_at)).toBe(true);
}

export function assertManuscript(manuscript: any): asserts manuscript is Manuscript {
  expect(manuscript).toBeDefined();
  expect(typeof manuscript).toBe('object');
  expect(isValidUUID(manuscript.id)).toBe(true);
  expect(isValidUUID(manuscript.journal_id)).toBe(true);
  expect(typeof manuscript.title).toBe('string');
  expect(Object.values(ManuscriptStatus)).toContain(manuscript.status);
  expect(typeof manuscript.submission_date).toBe('number');
  expect(typeof manuscript.is_fast_track_submission).toBe('boolean');
  expect(isValidISO8601(manuscript.created_at)).toBe(true);
  expect(isValidISO8601(manuscript.updated_at)).toBe(true);
}

export function assertReviewAssignment(assignment: any): asserts assignment is ReviewAssignment {
  expect(assignment).toBeDefined();
  expect(typeof assignment).toBe('object');
  expect(isValidUUID(assignment.id)).toBe(true);
  expect(isValidUUID(assignment.manuscript_id)).toBe(true);
  expect(isValidUUID(assignment.journal_id)).toBe(true);
  expect(typeof assignment.required_expertise).toBe('string');
  expect(Object.values(ReviewAssignmentStatus)).toContain(assignment.status);
  expect(Object.values(AnonymityLevel)).toContain(assignment.required_anonymity_level);
  expect(typeof assignment.due_date).toBe('number');
  expect(typeof assignment.revision_cycle).toBe('number');
  expect(isValidISO8601(assignment.created_at)).toBe(true);
  expect(isValidISO8601(assignment.updated_at)).toBe(true);
}

export function assertCertification(certification: any): asserts certification is Certification {
    expect(certification).toBeDefined();
    expect(typeof certification).toBe('object');
    expect(isValidUUID(certification.id)).toBe(true);
    expect(Object.values(CertificationName)).toContain(certification.name);
    expect(isValidDate(certification.granted_date)).toBe(true);
}

export function assertReviewerProfile(profile: any): asserts profile is ReviewerProfile {
  expect(profile).toBeDefined();
  expect(typeof profile).toBe('object');
  expect(isValidUUID(profile.id)).toBe(true);
  expect(isValidUUID(profile.journal_id)).toBe(true);
  expect(typeof profile.full_name).toBe('string');
  expect(typeof profile.institution).toBe('string');
  expect(Array.isArray(profile.expertise_areas)).toBe(true);
  profile.expertise_areas.forEach((area: any) => expect(typeof area).toBe('string'));
  expect(Array.isArray(profile.certifications)).toBe(true);
  profile.certifications.forEach(assertCertification);
  expect(isValidISO8601(profile.created_at)).toBe(true);
  expect(isValidISO8601(profile.updated_at)).toBe(true);
}

export function assertReview(review: any): asserts review is Review {
  expect(review).toBeDefined();
  expect(typeof review).toBe('object');
  expect(isValidUUID(review.id)).toBe(true);
  expect(isValidUUID(review.journal_id)).toBe(true);
  expect(isValidUUID(review.assignment_id)).toBe(true);
  expect(isValidUUID(review.reviewer_id)).toBe(true);
  expect(Object.values(ReviewStatus)).toContain(review.status);
  expect(typeof review.in_extra_revision_cycle).toBe('boolean');
  expect(typeof review.provisional_prestige_cost).toBe('number');
  if (review.final_prestige_cost !== null) {
    expect(typeof review.final_prestige_cost).toBe('number');
  }
  expect(isValidISO8601(review.created_at)).toBe(true);
  expect(isValidISO8601(review.updated_at)).toBe(true);
}

export function assertConflictOfInterest(conflict: any): asserts conflict is ConflictOfInterest {
  expect(conflict).toBeDefined();
  expect(typeof conflict).toBe('object');
  expect(isValidUUID(conflict.id)).toBe(true);
  expect(isValidUUID(conflict.journal_id)).toBe(true);
  expect(isValidUUID(conflict.entity_1_id)).toBe(true);
  expect(isValidUUID(conflict.entity_2_id)).toBe(true);
  expect(Object.values(ConflictOfInterestType)).toContain(conflict.conflict_type);
  if (conflict.reason !== null && conflict.reason !== undefined) {
    expect(typeof conflict.reason).toBe('string');
  }
  expect(isValidISO8601(conflict.created_at)).toBe(true);
}
