import { UserRole } from './types';

export interface ApiHeaders {
  'X-User-ID': string;
  'X-User-Role': UserRole;
  [key: string]: string;
}

export function buildUserHeaders(userId: string, userRole: UserRole): ApiHeaders {
  return {
    'X-User-ID': userId,
    'X-User-Role': userRole
  };
}

export function isISO8601Timestamp(str: string): boolean {
  const iso8601Pattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$/;
  return iso8601Pattern.test(str);
}
