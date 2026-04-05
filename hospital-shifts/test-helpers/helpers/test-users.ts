import { buildUserHeaders } from './utils';

/**
 * Standard test users used across the concurrency test suite.
 * These are pre-built headers that can be imported directly instead of
 * declaring them in every test file.
 */
export const TEST_USERS = {
  chargeNurseHeaders: buildUserHeaders('cn-1', 'ChargeNurse'),
  physicianHeaders: buildUserHeaders('physician-1', 'AttendingPhysician'),
  adminHeaders: buildUserHeaders('admin-1', 'HospitalAdministrator'),
} as const;
