import { v4 as uuidv4 } from 'uuid';
import {
  Journal,
  Manuscript,
  ReviewAssignment,
  ReviewerProfile,
  Review,
  ConflictOfInterest,
  Certification,
  CertificationName,
  CreateJournalPayload,
  CreateManuscriptPayload,
  CreateReviewAssignmentPayload,
  CreateReviewerProfilePayload,
  ReviewInvitationPayload,
  CreateConflictOfInterestPayload,
  AddCertificationPayload,
  UserRole,
  ConflictOfInterestType,
  ManuscriptStatus,
} from './types';
import { createUnixTimestamp, addDays, buildUserHeaders } from './utils';
import { handleApiResponse } from './validators';
import { apiClient } from './api-client';

const DEFAULTS = {
  JOURNAL_NAME: 'Journal of Feline Psychology',
  TOTAL_PRESTIGE: 1000,
  MANUSCRIPT_TITLE: 'The Fluffiness of Cats: A Quantitative Analysis',
  REQUIRED_EXPERTISE: 'Feline Psychology',
  REVIEWER_NAME: 'Dr. Whiskers',
  INSTITUTION: 'Cat-iversity',
  EXPERTISE_AREAS: ['Feline Psychology', 'Animal Behavior'],
  DUE_DATE_DAYS: 14,
};

export function createJournalPayload(
  overrides: Partial<CreateJournalPayload> = {}
): CreateJournalPayload {
  return {
    journal_name: DEFAULTS.JOURNAL_NAME,
    total_prestige: DEFAULTS.TOTAL_PRESTIGE,
    ...overrides,
  };
}

export function createManuscriptPayload(
  overrides: Partial<CreateManuscriptPayload> = {}
): CreateManuscriptPayload {
  return {
    title: DEFAULTS.MANUSCRIPT_TITLE,
    submission_date: createUnixTimestamp(0),
    is_fast_track_submission: false,
    ...overrides,
  };
}

export function createReviewAssignmentPayload(
  overrides: Partial<CreateReviewAssignmentPayload> = {}
): CreateReviewAssignmentPayload {
  return {
    required_expertise: DEFAULTS.REQUIRED_EXPERTISE,
    due_date: addDays(createUnixTimestamp(0), DEFAULTS.DUE_DATE_DAYS),
    ...overrides,
  };
}

export function createReviewerProfilePayload(
  overrides: Partial<CreateReviewerProfilePayload> = {}
): CreateReviewerProfilePayload {
  return {
    full_name: DEFAULTS.REVIEWER_NAME,
    institution: DEFAULTS.INSTITUTION,
    expertise_areas: DEFAULTS.EXPERTISE_AREAS,
    ...overrides,
  };
}

export function createCertificationPayload(
  name: CertificationName,
  overrides: Partial<AddCertificationPayload> = {}
): AddCertificationPayload {
    const today = new Date();
    const grantedDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return {
    name,
    granted_date: grantedDate.toISOString().split('T')[0],
    ...overrides,
  };
}

export function createReviewInvitationPayload(
  assignmentId: string,
  reviewerId: string,
  overrides: Partial<ReviewInvitationPayload> = {}
): ReviewInvitationPayload {
  return {
    assignment_id: assignmentId,
    reviewer_id: reviewerId,
    ...overrides,
  };
}

export function createConflictOfInterestPayload(
  entity1Id: string,
  entity2Id: string,
  overrides: Partial<CreateConflictOfInterestPayload> = {}
): CreateConflictOfInterestPayload {
  return {
    entity_1_id: entity1Id,
    entity_2_id: entity2Id,
    conflict_type: ConflictOfInterestType.INSTITUTIONAL,
    reason: 'Test conflict reason',
    ...overrides,
  };
}

export async function setupJournal(
  overrides: Partial<CreateJournalPayload> = {}
): Promise<Journal> {
  const editorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);
  const payload = createJournalPayload(overrides);
  const res = await apiClient.createJournal(payload, editorHeaders);
  return handleApiResponse<Journal>(res, 201);
}

export async function setupJournalInReview(
    overrides: Partial<CreateJournalPayload> = {}
  ): Promise<Journal> {
    const journal = await setupJournal(overrides);
    const editorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);
    const activatedRes = await apiClient.beginReview(journal.id, editorHeaders);
    return handleApiResponse<Journal>(activatedRes, 200);
}

export async function setupManuscript(
  journalId: string,
  overrides: Partial<CreateManuscriptPayload> = {}
): Promise<Manuscript> {
  const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
  const payload = createManuscriptPayload(overrides);
  const res = await apiClient.createManuscript(journalId, payload, sectionEditorHeaders);
  return handleApiResponse<Manuscript>(res, 201);
}

export async function setupReviewerProfile(
    journalId: string,
    overrides: Partial<CreateReviewerProfilePayload> = {}
): Promise<ReviewerProfile> {
    const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
    const payload = createReviewerProfilePayload(overrides);
    const res = await apiClient.createReviewerProfile(journalId, payload, sectionEditorHeaders);
    return handleApiResponse<ReviewerProfile>(res, 201);
}

export async function setupCustomJournalScenario(
    journalOverrides: Partial<CreateJournalPayload> = {},
    manuscriptOverrides: Partial<CreateManuscriptPayload> = {},
    manuscriptStatus?: ManuscriptStatus
  ) {
    const journal = await setupJournal(journalOverrides);
    const manuscript = await setupManuscript(journal.id, manuscriptOverrides);
    const reviewer = await setupReviewerProfile(journal.id);
    const editorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);
    const inReviewRes = await apiClient.beginReview(journal.id, editorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);
    const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
    const assignmentPayload = createReviewAssignmentPayload();
    const assignmentRes = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
    const assignment = handleApiResponse<ReviewAssignment>(assignmentRes, 201);

    if (manuscriptStatus) {
      await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: manuscriptStatus }, editorHeaders);
    }

    return { journal: inReviewJournal, manuscript, reviewer, assignment };
  }

export async function setupBasicJournalScenario(journalOverrides: Partial<CreateJournalPayload> = {}) {
  const journal = await setupJournal(journalOverrides);

  const manuscript = await setupManuscript(journal.id);

  const reviewer = await setupReviewerProfile(journal.id);

  const editorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);
  const inReviewRes = await apiClient.beginReview(journal.id, editorHeaders);
  const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

  const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
  const journalEditorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);

  const assignmentPayload = createReviewAssignmentPayload();
  const assignmentRes = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
  const assignment = handleApiResponse<ReviewAssignment>(assignmentRes, 201);

  await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

  return { journal: inReviewJournal, manuscript, reviewer, assignment };
}

export async function setupInvitedReview(
    options: {
        isExtraRevision?: boolean;
        journalPrestige?: number;
    } = {}
) {
    const { isExtraRevision = false, journalPrestige } = options;
    const journalOverrides = journalPrestige ? { total_prestige: journalPrestige } : {};

    const { journal, manuscript, reviewer, assignment } = await setupBasicJournalScenario(journalOverrides);
    const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
    const journalEditorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);

    let targetAssignment = assignment;
    let targetReviewer = reviewer;

    if (isExtraRevision) {
        const extraExpertise = 'extra-expertise';
        targetReviewer = await setupReviewerProfile(journal.id, {
            full_name: 'Extra Expert',
            expertise_areas: [extraExpertise],
        });
        for (let i = 0; i < 3; i++) {
            await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload({ required_expertise: `dummy-${i}` }), sectionEditorHeaders);
        }
        const extraAssignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload({ required_expertise: extraExpertise }), sectionEditorHeaders);
        targetAssignment = handleApiResponse<ReviewAssignment>(extraAssignmentRes, 201);
    }

    const initialJournalStateRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
    const initialJournalState = handleApiResponse<Journal>(initialJournalStateRes, 200);

    const invitationPayload = createReviewInvitationPayload(targetAssignment.id, targetReviewer.id);
    const reviewRes = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
    const review = handleApiResponse<Review>(reviewRes, 201);

    return { journal, manuscript, reviewer: targetReviewer, assignment: targetAssignment, review, initialJournalState };
}

export async function setupAcceptedReview() {
    const { journal, manuscript, reviewer, assignment, review } = await setupInvitedReview();
    const journalEditorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);

    const acceptedReviewRes = await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
    const acceptedReview = handleApiResponse<Review>(acceptedReviewRes, 200);

    return { journal, manuscript, reviewer, assignment, review: acceptedReview };
}
